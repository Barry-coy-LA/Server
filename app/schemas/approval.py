# app/schemas/approval.py - 实验审批系统数据模型
from pydantic import BaseModel, EmailStr, validator
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

class ApprovalStatus(str, Enum):
    """审批状态枚举"""
    PENDING = "pending"     # 待审批
    APPROVED = "approved"   # 已通过
    REJECTED = "rejected"   # 已驳回
    EXPIRED = "expired"     # 已过期

class ExperimentDataItem(BaseModel):
    """实验数据项"""
    parameter_name: str
    value: str
    unit: Optional[str] = None
    description: Optional[str] = None

class SubmitReportRequest(BaseModel):
    """提交审批请求模型"""
    report_id: str
    title: str
    content: str
    operator: str
    approver_email: EmailStr
    experiment_data: Optional[List[ExperimentDataItem]] = []
    
    # 邮件配置
    smtp_server: str
    smtp_port: int = 587
    from_email: EmailStr
    email_password: str
    use_tls: bool = True
    
    @validator('report_id')
    def validate_report_id(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('报告ID不能为空')
        return v.strip()
    
    @validator('title')
    def validate_title(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('报告标题不能为空')
        return v.strip()
    
    @validator('content')
    def validate_content(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('报告内容不能为空')
        return v.strip()
    
    @validator('operator')
    def validate_operator(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('操作员姓名不能为空')
        return v.strip()

class SubmitReportResponse(BaseModel):
    """提交审批响应模型"""
    success: bool
    message: str
    report_id: str
    approval_id: Optional[str] = None
    tokens_generated: bool = False
    email_sent: bool = False
    pdf_generated: bool = False
    error_details: Optional[str] = None

class ApprovalRecord(BaseModel):
    """审批记录模型"""
    id: str
    report_id: str
    title: str
    content: str
    operator: str
    approver_email: EmailStr
    
    # Token信息
    approve_token: str
    reject_token: str
    token_expires_at: datetime
    
    # 状态信息
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime
    processed_at: Optional[datetime] = None
    
    # 处理信息
    processor_ip: Optional[str] = None
    processor_user_agent: Optional[str] = None
    reason: Optional[str] = None  # 驳回原因
    
    # 文件信息
    pdf_path: Optional[str] = None
    pdf_file_size: Optional[int] = None
    
    # 请求信息
    submit_ip: Optional[str] = None
    submit_time: datetime
    
    def is_expired(self) -> bool:
        """检查Token是否已过期"""
        return datetime.now() > self.token_expires_at
    
    def can_be_processed(self) -> bool:
        """检查是否可以被处理"""
        return (
            self.status == ApprovalStatus.PENDING and
            not self.is_expired()
        )

class ApprovalActionResponse(BaseModel):
    """审批动作响应模型"""
    success: bool
    message: str
    report_id: str
    action: str  # approve/reject
    processed_at: datetime
    processor_ip: str

class ApprovalStatusQuery(BaseModel):
    """审批状态查询响应"""
    report_id: str
    status: ApprovalStatus
    approver_email: EmailStr
    created_at: datetime
    processed_at: Optional[datetime] = None
    reason: Optional[str] = None
    operator: str
    title: str

class EmailConfig(BaseModel):
    """邮件配置模型"""
    smtp_server: str
    smtp_port: int = 587
    username: str
    password: str
    use_tls: bool = True
    
    @validator('smtp_server')
    def validate_smtp_server(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('SMTP服务器不能为空')
        return v.strip()
    
    @validator('username')
    def validate_username(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('邮箱用户名不能为空')
        return v.strip()
    
    @validator('password')
    def validate_password(cls, v):
        if not v or len(v.strip()) == 0:
            raise ValueError('邮箱密码/授权码不能为空')
        return v

class PDFGenerationConfig(BaseModel):
    """PDF生成配置"""
    watermark_text: str = "实验报告 · 仅限内部审批使用"
    include_timestamp: bool = True
    include_qr_code: bool = False
    font_size: int = 12
    page_size: str = "A4"
    margins: Dict[str, float] = {
        "top": 72,
        "bottom": 72,
        "left": 72,
        "right": 72
    }

class SystemStats(BaseModel):
    """系统统计信息"""
    total_reports: int
    pending_approvals: int
    approved_reports: int
    rejected_reports: int
    expired_tokens: int
    today_submissions: int
    avg_approval_time_minutes: float

class ApprovalLogEntry(BaseModel):
    """审批日志条目"""
    id: str
    report_id: str
    action: str  # submit/approve/reject/view
    ip_address: str
    user_agent: Optional[str] = None
    timestamp: datetime
    details: Optional[Dict[str, Any]] = None

# 用于数据库存储的模型（可选，如果使用ORM）
class ApprovalRecordDB(BaseModel):
    """数据库存储用的审批记录模型"""
    id: str
    report_id: str
    title: str
    content: str
    operator: str
    approver_email: str
    approve_token: str
    reject_token: str
    token_expires_at: str  # 存储为ISO格式字符串
    status: str
    created_at: str
    processed_at: Optional[str] = None
    processor_ip: Optional[str] = None
    processor_user_agent: Optional[str] = None
    reason: Optional[str] = None
    pdf_path: Optional[str] = None
    pdf_file_size: Optional[int] = None
    submit_ip: Optional[str] = None
    submit_time: str
    
    @classmethod
    def from_approval_record(cls, record: ApprovalRecord) -> 'ApprovalRecordDB':
        """从ApprovalRecord转换为数据库存储格式"""
        return cls(
            id=record.id,
            report_id=record.report_id,
            title=record.title,
            content=record.content,
            operator=record.operator,
            approver_email=record.approver_email,
            approve_token=record.approve_token,
            reject_token=record.reject_token,
            token_expires_at=record.token_expires_at.isoformat(),
            status=record.status.value,
            created_at=record.created_at.isoformat(),
            processed_at=record.processed_at.isoformat() if record.processed_at else None,
            processor_ip=record.processor_ip,
            processor_user_agent=record.processor_user_agent,
            reason=record.reason,
            pdf_path=record.pdf_path,
            pdf_file_size=record.pdf_file_size,
            submit_ip=record.submit_ip,
            submit_time=record.submit_time.isoformat()
        )
    
    def to_approval_record(self) -> ApprovalRecord:
        """转换为ApprovalRecord对象"""
        return ApprovalRecord(
            id=self.id,
            report_id=self.report_id,
            title=self.title,
            content=self.content,
            operator=self.operator,
            approver_email=self.approver_email,
            approve_token=self.approve_token,
            reject_token=self.reject_token,
            token_expires_at=datetime.fromisoformat(self.token_expires_at),
            status=ApprovalStatus(self.status),
            created_at=datetime.fromisoformat(self.created_at),
            processed_at=datetime.fromisoformat(self.processed_at) if self.processed_at else None,
            processor_ip=self.processor_ip,
            processor_user_agent=self.processor_user_agent,
            reason=self.reason,
            pdf_path=self.pdf_path,
            pdf_file_size=self.pdf_file_size,
            submit_ip=self.submit_ip,
            submit_time=datetime.fromisoformat(self.submit_time)
        )