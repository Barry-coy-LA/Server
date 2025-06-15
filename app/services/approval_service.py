# app/services/approval_service.py - 修复后的审批服务（单例模式）
import json
import uuid
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any
import logging
import aiofiles

from app.schemas.approval import (
    ApprovalRecord, 
    ApprovalRecordDB, 
    ApprovalStatus,
    ApprovalLogEntry,
    SystemStats
)

logger = logging.getLogger(__name__)

class ApprovalService:
    """实验审批核心服务 - 单例模式"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        # 避免重复初始化
        if self._initialized:
            return
            
        self.data_dir = Path("Data/approval")
        self.records_file = self.data_dir / "approval_records.json"
        self.logs_file = self.data_dir / "approval_logs.json"
        self.stats_file = self.data_dir / "approval_stats.json"
        
        # 确保数据目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 内存缓存
        self._records_cache: Dict[str, ApprovalRecord] = {}
        self._logs_cache: List[ApprovalLogEntry] = []
        self._cache_initialized = False
        
        # Token有效期（分钟）
        self.token_expiry_minutes = 30
        
        # 标记为已初始化
        self._initialized = True
        logger.info("审批服务已初始化（单例模式）")
    
    async def _ensure_cache_initialized(self):
        """确保缓存已初始化（只执行一次）"""
        if not self._cache_initialized:
            await self._load_records()
            await self._load_logs()
            self._cache_initialized = True
            logger.info("审批服务缓存初始化完成")
    
    # ... 其他方法保持不变 ...
    
    async def _load_records(self):
        """从文件加载审批记录"""
        try:
            if self.records_file.exists():
                async with aiofiles.open(self.records_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    if content.strip():
                        data = json.loads(content)
                        for record_data in data:
                            try:
                                db_record = ApprovalRecordDB(**record_data)
                                approval_record = db_record.to_approval_record()
                                self._records_cache[approval_record.id] = approval_record
                            except Exception as e:
                                logger.warning(f"跳过无效审批记录: {e}")
                logger.info(f"成功加载 {len(self._records_cache)} 条审批记录")
            else:
                logger.info("审批记录文件不存在，创建新文件")
                await self._save_records()
                
        except Exception as e:
            logger.error(f"加载审批记录失败: {e}")
            self._records_cache = {}
    
    async def _save_records(self):
        """保存审批记录到文件"""
        try:
            # 转换为数据库格式
            data = []
            for record in self._records_cache.values():
                db_record = ApprovalRecordDB.from_approval_record(record)
                data.append(db_record.dict())
            
            # 异步写入文件
            async with aiofiles.open(self.records_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(data, indent=2, ensure_ascii=False))
                
        except Exception as e:
            logger.error(f"保存审批记录失败: {e}")
    
    async def _load_logs(self):
        """从文件加载审批日志"""
        try:
            if self.logs_file.exists():
                async with aiofiles.open(self.logs_file, 'r', encoding='utf-8') as f:
                    content = await f.read()
                    if content.strip():
                        data = json.loads(content)
                        for log_data in data:
                            try:
                                # 处理时间戳
                                if isinstance(log_data.get('timestamp'), str):
                                    log_data['timestamp'] = datetime.fromisoformat(log_data['timestamp'])
                                
                                log_entry = ApprovalLogEntry(**log_data)
                                self._logs_cache.append(log_entry)
                            except Exception as e:
                                logger.warning(f"跳过无效日志记录: {e}")
                logger.info(f"成功加载 {len(self._logs_cache)} 条审批日志")
            else:
                logger.info("审批日志文件不存在，创建新文件")
                await self._save_logs()
                
        except Exception as e:
            logger.error(f"加载审批日志失败: {e}")
            self._logs_cache = []
    
    async def _save_logs(self):
        """保存审批日志到文件"""
        try:
            # 只保留最近1000条日志
            logs_to_save = self._logs_cache[-1000:] if len(self._logs_cache) > 1000 else self._logs_cache
            
            # 转换为可序列化格式
            data = []
            for log_entry in logs_to_save:
                log_dict = log_entry.dict()
                # 确保时间戳是字符串格式
                if isinstance(log_dict['timestamp'], datetime):
                    log_dict['timestamp'] = log_dict['timestamp'].isoformat()
                data.append(log_dict)
            
            # 异步写入文件
            async with aiofiles.open(self.logs_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(data, indent=2, ensure_ascii=False))
                
        except Exception as e:
            logger.error(f"保存审批日志失败: {e}")
    
    async def get_approval_statistics(self) -> SystemStats:
        """获取审批系统统计信息"""
        await self._ensure_cache_initialized()
        
        try:
            now = datetime.now()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            
            # 统计各种状态的数量
            total_reports = len(self._records_cache)
            pending_approvals = 0
            approved_reports = 0
            rejected_reports = 0
            expired_tokens = 0
            today_submissions = 0
            
            approval_times = []  # 用于计算平均审批时间
            
            for record in self._records_cache.values():
                # 统计状态
                if record.status == ApprovalStatus.PENDING:
                    if record.is_expired():
                        expired_tokens += 1
                    else:
                        pending_approvals += 1
                elif record.status == ApprovalStatus.APPROVED:
                    approved_reports += 1
                    # 计算审批时间
                    if record.processed_at:
                        approval_time = (record.processed_at - record.created_at).total_seconds() / 60
                        approval_times.append(approval_time)
                elif record.status == ApprovalStatus.REJECTED:
                    rejected_reports += 1
                    # 计算审批时间
                    if record.processed_at:
                        approval_time = (record.processed_at - record.created_at).total_seconds() / 60
                        approval_times.append(approval_time)
                
                # 统计今日提交
                if record.created_at >= today_start:
                    today_submissions += 1
            
            # 计算平均审批时间
            avg_approval_time = sum(approval_times) / len(approval_times) if approval_times else 0.0
            
            return SystemStats(
                total_reports=total_reports,
                pending_approvals=pending_approvals,
                approved_reports=approved_reports,
                rejected_reports=rejected_reports,
                expired_tokens=expired_tokens,
                today_submissions=today_submissions,
                avg_approval_time_minutes=round(avg_approval_time, 2)
            )
            
        except Exception as e:
            logger.error(f"获取审批统计信息失败: {e}")
            return SystemStats(
                total_reports=0,
                pending_approvals=0,
                approved_reports=0,
                rejected_reports=0,
                expired_tokens=0,
                today_submissions=0,
                avg_approval_time_minutes=0.0
            )

# 全局单例实例
_approval_service_instance = None

def get_approval_service() -> ApprovalService:
    """获取审批服务单例实例"""
    global _approval_service_instance
    if _approval_service_instance is None:
        _approval_service_instance = ApprovalService()
    return _approval_service_instance