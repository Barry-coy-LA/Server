# app/services/approval_service.py - 实验审批核心服务
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
    """实验审批核心服务"""
    
    def __init__(self):
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
        
        logger.info("审批服务已初始化")
    
    async def _ensure_cache_initialized(self):
        """确保缓存已初始化"""
        if not self._cache_initialized:
            await self._load_records()
            await self._load_logs()
            self._cache_initialized = True
    
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
    
    async def _log_action(
        self, 
        report_id: str, 
        action: str, 
        ip_address: str, 
        user_agent: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """记录审批动作日志"""
        try:
            log_entry = ApprovalLogEntry(
                id=str(uuid.uuid4()),
                report_id=report_id,
                action=action,
                ip_address=ip_address,
                user_agent=user_agent,
                timestamp=datetime.now(),
                details=details or {}
            )
            
            self._logs_cache.append(log_entry)
            
            # 异步保存日志（不等待完成）
            asyncio.create_task(self._save_logs())
            
        except Exception as e:
            logger.error(f"记录审批日志失败: {e}")
    
    async def create_approval_request(
        self,
        report_id: str,
        title: str,
        content: str,
        operator: str,
        approver_email: str,
        pdf_path: str,
        client_ip: str
    ) -> ApprovalRecord:
        """创建审批请求"""
        await self._ensure_cache_initialized()
        
        try:
            # 检查是否已存在相同report_id的记录
            existing_record = await self.get_approval_by_report_id(report_id)
            if existing_record and existing_record.status == ApprovalStatus.PENDING:
                raise ValueError(f"报告 {report_id} 已存在待审批记录")
            
            # 生成唯一Token
            approve_token = str(uuid.uuid4())
            reject_token = str(uuid.uuid4())
            
            # 创建审批记录
            approval_record = ApprovalRecord(
                id=str(uuid.uuid4()),
                report_id=report_id,
                title=title,
                content=content,
                operator=operator,
                approver_email=approver_email,
                approve_token=approve_token,
                reject_token=reject_token,
                token_expires_at=datetime.now() + timedelta(minutes=self.token_expiry_minutes),
                status=ApprovalStatus.PENDING,
                created_at=datetime.now(),
                pdf_path=pdf_path,
                submit_ip=client_ip,
                submit_time=datetime.now()
            )
            
            # 保存到缓存
            self._records_cache[approval_record.id] = approval_record
            
            # 异步保存到文件
            asyncio.create_task(self._save_records())
            
            # 记录日志
            await self._log_action(
                report_id=report_id,
                action="submit",
                ip_address=client_ip,
                details={
                    "operator": operator,
                    "approver_email": approver_email,
                    "title": title
                }
            )
            
            logger.info(f"创建审批请求成功 - {report_id}")
            return approval_record
            
        except Exception as e:
            logger.error(f"创建审批请求失败: {e}")
            raise
    
    async def get_approval_by_token(self, token: str, token_type: str) -> Optional[ApprovalRecord]:
        """根据Token获取审批记录"""
        await self._ensure_cache_initialized()
        
        try:
            for record in self._records_cache.values():
                if token_type == 'approve' and record.approve_token == token:
                    return record
                elif token_type == 'reject' and record.reject_token == token:
                    return record
            
            return None
            
        except Exception as e:
            logger.error(f"根据Token获取审批记录失败: {e}")
            return None
    
    async def get_approval_by_report_id(self, report_id: str) -> Optional[ApprovalRecord]:
        """根据报告ID获取审批记录"""
        await self._ensure_cache_initialized()
        
        try:
            for record in self._records_cache.values():
                if record.report_id == report_id:
                    return record
            
            return None
            
        except Exception as e:
            logger.error(f"根据报告ID获取审批记录失败: {e}")
            return None
    
    async def process_approval(
        self,
        approval_record: ApprovalRecord,
        action: str,  # 'approved' or 'rejected'
        ip_address: str,
        user_agent: str,
        reason: Optional[str] = None
    ):
        """处理审批动作"""
        await self._ensure_cache_initialized()
        
        try:
            # 检查记录是否可以被处理
            if not approval_record.can_be_processed():
                raise ValueError("该审批记录无法被处理（已过期或已处理）")
            
            # 更新记录状态
            approval_record.status = ApprovalStatus.APPROVED if action == 'approved' else ApprovalStatus.REJECTED
            approval_record.processed_at = datetime.now()
            approval_record.processor_ip = ip_address
            approval_record.processor_user_agent = user_agent
            approval_record.reason = reason
            
            # 更新缓存
            self._records_cache[approval_record.id] = approval_record
            
            # 异步保存到文件
            asyncio.create_task(self._save_records())
            
            # 记录日志
            await self._log_action(
                report_id=approval_record.report_id,
                action=action,
                ip_address=ip_address,
                user_agent=user_agent,
                details={
                    "approver_email": approval_record.approver_email,
                    "reason": reason,
                    "processed_at": approval_record.processed_at.isoformat()
                }
            )
            
            logger.info(f"审批处理完成 - {approval_record.report_id}: {action}")
            
        except Exception as e:
            logger.error(f"处理审批失败: {e}")
            raise
    
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
    
    async def get_recent_approvals(self, limit: int = 50) -> List[ApprovalRecord]:
        """获取最近的审批记录"""
        await self._ensure_cache_initialized()
        
        try:
            # 按创建时间降序排序
            sorted_records = sorted(
                self._records_cache.values(),
                key=lambda x: x.created_at,
                reverse=True
            )
            
            return sorted_records[:limit]
            
        except Exception as e:
            logger.error(f"获取最近审批记录失败: {e}")
            return []
    
    async def get_approval_logs(
        self, 
        report_id: Optional[str] = None, 
        limit: int = 100
    ) -> List[ApprovalLogEntry]:
        """获取审批日志"""
        await self._ensure_cache_initialized()
        
        try:
            logs = self._logs_cache.copy()
            
            # 如果指定了报告ID，过滤日志
            if report_id:
                logs = [log for log in logs if log.report_id == report_id]
            
            # 按时间降序排序
            logs.sort(key=lambda x: x.timestamp, reverse=True)
            
            return logs[:limit]
            
        except Exception as e:
            logger.error(f"获取审批日志失败: {e}")
            return []
    
    async def cleanup_expired_records(self):
        """清理过期的审批记录"""
        await self._ensure_cache_initialized()
        
        try:
            now = datetime.now()
            expired_count = 0
            
            for record_id, record in list(self._records_cache.items()):
                if (record.status == ApprovalStatus.PENDING and 
                    record.is_expired()):
                    # 标记为过期
                    record.status = ApprovalStatus.EXPIRED
                    expired_count += 1
            
            if expired_count > 0:
                # 保存更新后的记录
                await self._save_records()
                logger.info(f"清理了 {expired_count} 条过期审批记录")
            
            return expired_count
            
        except Exception as e:
            logger.error(f"清理过期记录失败: {e}")
            return 0
    
    async def delete_old_records(self, days: int = 90):
        """删除旧的审批记录"""
        await self._ensure_cache_initialized()
        
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            deleted_count = 0
            
            for record_id in list(self._records_cache.keys()):
                record = self._records_cache[record_id]
                if record.created_at < cutoff_date:
                    # 删除记录
                    del self._records_cache[record_id]
                    deleted_count += 1
                    
                    # 同时删除相关的PDF文件
                    if record.pdf_path and Path(record.pdf_path).exists():
                        try:
                            Path(record.pdf_path).unlink()
                        except Exception as e:
                            logger.warning(f"删除PDF文件失败: {e}")
            
            if deleted_count > 0:
                # 保存更新后的记录
                await self._save_records()
                logger.info(f"删除了 {deleted_count} 条旧审批记录")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"删除旧记录失败: {e}")
            return 0