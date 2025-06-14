# app/services/usage_tracker.py - 完整修复版本
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pydantic import BaseModel
from enum import Enum
import json
import asyncio
from pathlib import Path
import aiofiles
import logging
import uuid

logger = logging.getLogger(__name__)

class ServiceType(str, Enum):
    OCR = "ocr"
    FACE_RECOGNITION = "face_recognition"
    FACE_REGISTER = "face_register" 
    FACE_VERIFY = "face_verify"
    FACE_DETECT = "face_detect"
    AGI_CHAT = "agi_chat"  # 为未来的AGI功能预留
    MCP_TOOL = "mcp_tool"  # 为未来的MCP功能预留
    HOST_DATA = "host_data"  # 上位机数据

class UsageRecord(BaseModel):
    """使用记录模型"""
    id: str
    service_type: str  # 改为str，避免序列化问题
    timestamp: datetime
    client_ip: str
    user_agent: Optional[str] = None
    request_data: Dict[str, Any] = {}
    response_data: Dict[str, Any] = {}
    processing_time: float = 0.0  # 处理时间(秒)
    success: bool = True
    error_message: Optional[str] = None
    file_size: Optional[int] = None  # 上传文件大小
    file_type: Optional[str] = None  # 文件类型
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class UsageTracker:
    """使用记录追踪器"""
    
    def __init__(self):
        self.records: List[UsageRecord] = []
        self.data_file = Path("Data/usage_records.json")
        self.max_records = 10000  # 最大保存记录数
        self._lock = None  # 延迟初始化
        self._initialized = False
        
        # 确保数据目录存在
        self.data_file.parent.mkdir(exist_ok=True)
    
    async def _ensure_lock(self):
        """确保锁已初始化"""
        if self._lock is None:
            self._lock = asyncio.Lock()
    
    async def initialize(self):
        """初始化追踪器"""
        if self._initialized:
            return
            
        try:
            await self._ensure_lock()
            await self._load_records()
            self._initialized = True
            logger.info(f"使用追踪器初始化完成，加载了 {len(self.records)} 条记录")
        except Exception as e:
            logger.error(f"使用追踪器初始化失败: {e}")
            self._initialized = True  # 即使失败也标记为已初始化，避免重复尝试
    
    async def _load_records(self):
        """加载历史记录"""
        try:
            if self.data_file.exists():
                # 使用同步文件读取，避免aiofiles问题
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if content.strip():
                        data = json.loads(content)
                        self.records = []
                        for record_data in data:
                            try:
                                # 处理时间戳
                                if isinstance(record_data.get('timestamp'), str):
                                    record_data['timestamp'] = datetime.fromisoformat(record_data['timestamp'])
                                
                                # 确保service_type是字符串
                                if 'service_type' in record_data:
                                    record_data['service_type'] = str(record_data['service_type'])
                                
                                record = UsageRecord(**record_data)
                                self.records.append(record)
                            except Exception as e:
                                logger.warning(f"跳过无效记录: {e}")
                        logger.info(f"成功加载 {len(self.records)} 条使用记录")
        except Exception as e:
            logger.error(f"加载使用记录失败: {e}")
            self.records = []
    
    async def _save_records(self):
        """保存记录到文件"""
        try:
            await self._ensure_lock()
            async with self._lock:
                # 只保存最新的记录
                records_to_save = self.records[-self.max_records:] if len(self.records) > self.max_records else self.records
                
                # 转换为可序列化的格式
                data = []
                for record in records_to_save:
                    record_dict = record.dict()
                    # 确保时间戳是字符串格式
                    if isinstance(record_dict['timestamp'], datetime):
                        record_dict['timestamp'] = record_dict['timestamp'].isoformat()
                    data.append(record_dict)
                
                # 使用同步写入，避免aiofiles问题
                with open(self.data_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    
        except Exception as e:
            logger.error(f"保存使用记录失败: {e}")
    
    async def record_usage(self, record: UsageRecord):
        """记录使用情况"""
        # 确保已初始化
        if not self._initialized:
            await self.initialize()
            
        try:
            await self._ensure_lock()
            async with self._lock:
                self.records.append(record)
                
                # 如果记录太多，删除旧记录
                if len(self.records) > self.max_records:
                    self.records = self.records[-self.max_records:]
            
            # 异步保存（不等待完成）
            asyncio.create_task(self._save_records())
            
        except Exception as e:
            logger.error(f"记录使用情况失败: {e}")
    
    async def get_records(
        self, 
        service_type: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[UsageRecord]:
        """获取使用记录"""
        # 确保已初始化
        if not self._initialized:
            await self.initialize()
            
        try:
            await self._ensure_lock()
            async with self._lock:
                filtered_records = self.records.copy()
            
            # 过滤条件
            if service_type:
                filtered_records = [r for r in filtered_records if r.service_type == service_type]
            
            if start_time:
                filtered_records = [r for r in filtered_records if r.timestamp >= start_time]
            
            if end_time:
                filtered_records = [r for r in filtered_records if r.timestamp <= end_time]
            
            # 排序和分页
            filtered_records.sort(key=lambda x: x.timestamp, reverse=True)
            return filtered_records[offset:offset + limit]
            
        except Exception as e:
            logger.error(f"获取使用记录失败: {e}")
            return []
    
    async def get_statistics(self, hours: int = 24) -> Dict[str, Any]:
        """获取使用统计"""
        # 确保已初始化
        if not self._initialized:
            await self.initialize()
            
        try:
            now = datetime.now()
            start_time = now - timedelta(hours=hours)
            
            await self._ensure_lock()
            async with self._lock:
                recent_records = [
                    r for r in self.records 
                    if r.timestamp >= start_time
                ]
            
            # 统计数据
            total_requests = len(recent_records)
            success_requests = len([r for r in recent_records if r.success])
            failed_requests = total_requests - success_requests
            
            # 按服务类型统计
            by_service = {}
            service_types = set(r.service_type for r in recent_records)
            for service_type in service_types:
                service_records = [r for r in recent_records if r.service_type == service_type]
                if service_records:
                    by_service[service_type] = {
                        "count": len(service_records),
                        "success": len([r for r in service_records if r.success]),
                        "failed": len([r for r in service_records if not r.success]),
                        "avg_time": sum(r.processing_time for r in service_records) / len(service_records)
                    }
            
            # 按小时统计
            by_hour = {}
            for record in recent_records:
                hour_key = record.timestamp.strftime("%H:00")
                if hour_key not in by_hour:
                    by_hour[hour_key] = 0
                by_hour[hour_key] += 1
            
            # 平均处理时间和文件大小
            avg_processing_time = 0.0
            total_file_size = 0
            
            if recent_records:
                avg_processing_time = sum(r.processing_time for r in recent_records) / len(recent_records)
                total_file_size = sum(r.file_size or 0 for r in recent_records)
            
            stats = {
                "total_requests": total_requests,
                "success_requests": success_requests,
                "failed_requests": failed_requests,
                "by_service": by_service,
                "by_hour": by_hour,
                "avg_processing_time": avg_processing_time,
                "total_file_size": total_file_size
            }
            
            logger.debug(f"生成统计数据: 总请求{total_requests}, 成功{success_requests}, 失败{failed_requests}")
            return stats
            
        except Exception as e:
            logger.error(f"获取统计数据失败: {e}")
            return {
                "total_requests": 0,
                "success_requests": 0,
                "failed_requests": 0,
                "by_service": {},
                "by_hour": {},
                "avg_processing_time": 0.0,
                "total_file_size": 0
            }
    
    async def create_record(
        self,
        service_type: str,
        client_ip: str = "unknown",
        user_agent: Optional[str] = None,
        processing_time: float = 0.0,
        success: bool = True,
        error_message: Optional[str] = None,
        file_size: Optional[int] = None,
        file_type: Optional[str] = None,
        request_data: Dict[str, Any] = None,
        response_data: Dict[str, Any] = None
    ) -> UsageRecord:
        """创建使用记录"""
        record = UsageRecord(
            id=str(uuid.uuid4()),
            service_type=str(service_type),  # 确保是字符串
            timestamp=datetime.now(),
            client_ip=client_ip,
            user_agent=user_agent,
            processing_time=processing_time,
            success=success,
            error_message=error_message,
            file_size=file_size,
            file_type=file_type,
            request_data=request_data or {},
            response_data=response_data or {}
        )
        
        await self.record_usage(record)
        return record

# 全局使用追踪器实例
usage_tracker = UsageTracker()

# 简化的装饰器函数
def track_usage_simple(service_type: str):
    """简化的使用追踪装饰器"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            start_time = datetime.now()
            
            # 尝试获取请求信息
            request = None
            client_ip = "unknown"
            user_agent = None
            file_size = None
            file_type = None
            
            # 从参数中提取Request对象和文件信息
            for arg in args:
                if hasattr(arg, 'client') and hasattr(arg, 'headers'):
                    request = arg
                    client_ip = request.client.host if request.client else "unknown"
                    user_agent = request.headers.get("user-agent")
                    break
            
            # 从kwargs中提取文件信息
            if 'file' in kwargs:
                file = kwargs['file']
                if hasattr(file, 'size'):
                    file_size = file.size
                if hasattr(file, 'content_type'):
                    file_type = file.content_type
            
            try:
                # 执行原函数
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                
                # 计算处理时间
                processing_time = (datetime.now() - start_time).total_seconds()
                
                # 创建成功记录
                await usage_tracker.create_record(
                    service_type=str(service_type),
                    client_ip=client_ip,
                    user_agent=user_agent,
                    processing_time=processing_time,
                    success=True,
                    file_size=file_size,
                    file_type=file_type,
                    response_data={"status": "success"}
                )
                
                return result
                
            except Exception as e:
                # 计算处理时间
                processing_time = (datetime.now() - start_time).total_seconds()
                
                # 创建失败记录
                await usage_tracker.create_record(
                    service_type=str(service_type),
                    client_ip=client_ip,
                    user_agent=user_agent,
                    processing_time=processing_time,
                    success=False,
                    error_message=str(e),
                    file_size=file_size,
                    file_type=file_type
                )
                
                # 重新抛出异常
                raise e
        
        return wrapper
    return decorator