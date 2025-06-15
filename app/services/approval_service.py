# app/services/approval_service.py - 重新设计的审批服务
import sqlite3
import uuid
import asyncio
import smtplib
import ssl
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import logging
import ipaddress
import json
from dataclasses import dataclass, asdict
from contextlib import asynccontextmanager

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT

logger = logging.getLogger(__name__)

@dataclass
class ApprovalRequest:
    """审批请求数据模型"""
    report_id: str
    title: str
    content: str
    operator: str
    approver_email: str
    smtp_server: str
    smtp_port: int
    from_email: str
    email_password: str
    use_tls: bool = True
    client_ip: str = "unknown"
    
@dataclass
class ApprovalRecord:
    """审批记录数据模型"""
    id: str
    report_id: str
    title: str
    content: str
    operator: str
    approver_email: str
    approve_token: str
    reject_token: str
    status: str  # pending, approved, rejected, expired
    created_at: datetime
    processed_at: Optional[datetime] = None
    processor_ip: Optional[str] = None
    processor_user_agent: Optional[str] = None
    reason: Optional[str] = None  # 驳回原因
    pdf_path: Optional[str] = None
    client_ip: str = "unknown"
    
    def is_expired(self) -> bool:
        """检查是否已过期（30分钟）"""
        return datetime.now() > (self.created_at + timedelta(minutes=30))

class ApprovalDatabase:
    """审批数据库管理"""
    
    def __init__(self, db_path: str = "Data/approval/approval.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
    
    def _init_database(self):
        """初始化数据库表"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS approval_records (
                    id TEXT PRIMARY KEY,
                    report_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    operator TEXT NOT NULL,
                    approver_email TEXT NOT NULL,
                    approve_token TEXT UNIQUE NOT NULL,
                    reject_token TEXT UNIQUE NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP NOT NULL,
                    processed_at TIMESTAMP,
                    processor_ip TEXT,
                    processor_user_agent TEXT,
                    reason TEXT,
                    pdf_path TEXT,
                    client_ip TEXT DEFAULT 'unknown'
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS approval_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    ip_address TEXT NOT NULL,
                    user_agent TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    details TEXT
                )
            ''')
            
            # 创建索引
            conn.execute('CREATE INDEX IF NOT EXISTS idx_report_id ON approval_records(report_id)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_tokens ON approval_records(approve_token, reject_token)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_status ON approval_records(status)')
    
    def save_record(self, record: ApprovalRecord) -> bool:
        """保存审批记录"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT INTO approval_records 
                    (id, report_id, title, content, operator, approver_email, 
                     approve_token, reject_token, status, created_at, 
                     processed_at, processor_ip, processor_user_agent, 
                     reason, pdf_path, client_ip)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    record.id, record.report_id, record.title, record.content,
                    record.operator, record.approver_email, record.approve_token,
                    record.reject_token, record.status, record.created_at,
                    record.processed_at, record.processor_ip, record.processor_user_agent,
                    record.reason, record.pdf_path, record.client_ip
                ))
                return True
        except Exception as e:
            logger.error(f"保存审批记录失败: {e}")
            return False
    
    def get_record_by_token(self, token: str, token_type: str) -> Optional[ApprovalRecord]:
        """根据token获取审批记录"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                column = f"{token_type}_token"
                cursor = conn.execute(f'''
                    SELECT * FROM approval_records 
                    WHERE {column} = ? AND status = 'pending'
                ''', (token,))
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                return ApprovalRecord(
                    id=row['id'],
                    report_id=row['report_id'],
                    title=row['title'],
                    content=row['content'],
                    operator=row['operator'],
                    approver_email=row['approver_email'],
                    approve_token=row['approve_token'],
                    reject_token=row['reject_token'],
                    status=row['status'],
                    created_at=datetime.fromisoformat(row['created_at']),
                    processed_at=datetime.fromisoformat(row['processed_at']) if row['processed_at'] else None,
                    processor_ip=row['processor_ip'],
                    processor_user_agent=row['processor_user_agent'],
                    reason=row['reason'],
                    pdf_path=row['pdf_path'],
                    client_ip=row['client_ip'] or 'unknown'
                )
        except Exception as e:
            logger.error(f"查询审批记录失败: {e}")
            return None
    
    def update_record_status(self, token: str, token_type: str, status: str, 
                           processor_ip: str, user_agent: str, reason: str = None) -> bool:
        """更新审批记录状态"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                column = f"{token_type}_token"
                conn.execute(f'''
                    UPDATE approval_records 
                    SET status = ?, processed_at = ?, processor_ip = ?, 
                        processor_user_agent = ?, reason = ?
                    WHERE {column} = ? AND status = 'pending'
                ''', (status, datetime.now(), processor_ip, user_agent, reason, token))
                return conn.total_changes > 0
        except Exception as e:
            logger.error(f"更新审批记录失败: {e}")
            return False
    
    def log_action(self, report_id: str, action: str, ip_address: str, 
                   user_agent: str = None, details: str = None):
        """记录审批操作日志"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('''
                    INSERT INTO approval_logs 
                    (report_id, action, ip_address, user_agent, details)
                    VALUES (?, ?, ?, ?, ?)
                ''', (report_id, action, ip_address, user_agent, details))
        except Exception as e:
            logger.error(f"记录操作日志失败: {e}")

class PDFGenerator:
    """PDF报告生成器"""
    
    def __init__(self, output_dir: str = "Data/approval/reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.styles = getSampleStyleSheet()
        self._setup_styles()
    
    def _setup_styles(self):
        """设置PDF样式"""
        self.title_style = ParagraphStyle(
            'CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=18,
            spaceAfter=30,
            alignment=TA_CENTER,
            textColor=colors.darkblue
        )
        
        self.watermark_style = ParagraphStyle(
            'Watermark',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=colors.lightgrey,
            alignment=TA_CENTER
        )
    
    def generate_report_pdf(self, request: ApprovalRequest) -> Path:
        """生成实验报告PDF"""
        filename = f"report_{request.report_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = self.output_dir / filename
        
        doc = SimpleDocTemplate(str(pdf_path), pagesize=A4)
        story = []
        
        # 水印
        watermark = "🔒 实验报告 · 仅限内部审批使用"
        story.append(Paragraph(watermark, self.watermark_style))
        story.append(Spacer(1, 20))
        
        # 标题
        story.append(Paragraph(request.title, self.title_style))
        story.append(Spacer(1, 20))
        
        # 报告信息表
        info_data = [
            ['报告编号:', request.report_id],
            ['操作员:', request.operator],
            ['生成时间:', datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")],
            ['审批人:', request.approver_email],
            ['状态:', '待审批']
        ]
        
        info_table = Table(info_data, colWidths=[2*inch, 4*inch])
        info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        story.append(info_table)
        story.append(Spacer(1, 30))
        
        # 报告内容
        story.append(Paragraph("实验内容", self.styles['Heading2']))
        story.append(Paragraph(request.content, self.styles['Normal']))
        story.append(Spacer(1, 30))
        
        # 页脚
        footer_text = "本报告由TianMu工业AGI试验台自动生成，仅用于内部审批流程"
        story.append(Paragraph(footer_text, self.watermark_style))
        
        doc.build(story)
        return pdf_path

class EmailSender:
    """邮件发送器"""
    
    def __init__(self, local_ip: str = "127.0.0.1", port: int = 8000):
        self.local_ip = local_ip
        self.port = port
    
    def send_approval_email(self, request: ApprovalRequest, approve_token: str, 
                          reject_token: str, pdf_path: Path) -> bool:
        """发送审批邮件"""
        try:
            # 创建邮件
            msg = MIMEMultipart('alternative')
            msg['From'] = request.from_email
            msg['To'] = request.approver_email
            msg['Subject'] = f"实验报告审批 - {request.title} ({request.report_id})"
            
            # 生成审批链接
            approve_url = f"http://{self.local_ip}:{self.port}/approval/approve?token={approve_token}"
            reject_url = f"http://{self.local_ip}:{self.port}/approval/reject?token={reject_token}"
            
            # HTML邮件内容
            html_content = self._generate_email_html(
                request, approve_url, reject_url
            )
            
            # 纯文本内容
            text_content = self._generate_email_text(
                request, approve_url, reject_url
            )
            
            # 添加邮件内容
            part1 = MIMEText(text_content, 'plain', 'utf-8')
            part2 = MIMEText(html_content, 'html', 'utf-8')
            
            msg.attach(part1)
            msg.attach(part2)
            
            # 添加PDF附件
            if pdf_path.exists():
                with open(pdf_path, "rb") as attachment:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment.read())
                
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename= "report_{request.report_id}.pdf"'
                )
                msg.attach(part)
            
            # 发送邮件
            self._send_smtp_email(msg, request)
            return True
            
        except Exception as e:
            logger.error(f"发送审批邮件失败: {e}")
            return False
    
    def _generate_email_html(self, request: ApprovalRequest, 
                           approve_url: str, reject_url: str) -> str:
        """生成HTML邮件内容"""
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
        
        return f'''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>实验报告审批</title>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #007bff; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }}
        .content {{ background: #f8f9fa; padding: 30px; border-radius: 0 0 8px 8px; }}
        .info-table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        .info-table td {{ padding: 10px; border: 1px solid #ddd; }}
        .info-table .label {{ background: #e9ecef; font-weight: bold; width: 120px; }}
        .buttons {{ text-align: center; margin: 30px 0; }}
        .btn {{ display: inline-block; padding: 15px 30px; margin: 0 10px; text-decoration: none; border-radius: 5px; font-weight: bold; }}
        .btn-approve {{ background: #28a745; color: white; }}
        .btn-reject {{ background: #dc3545; color: white; }}
        .warning {{ background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 20px 0; }}
        .footer {{ text-align: center; font-size: 12px; color: #666; margin-top: 30px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🔬 实验报告审批通知</h1>
        <p>TianMu工业AGI试验台 · 审批系统</p>
    </div>
    
    <div class="content">
        <p>尊敬的审批人员，您好！</p>
        <p>一份实验报告需要您的审批，具体信息如下：</p>
        
        <table class="info-table">
            <tr><td class="label">报告编号:</td><td>{request.report_id}</td></tr>
            <tr><td class="label">报告标题:</td><td>{request.title}</td></tr>
            <tr><td class="label">操作员:</td><td>{request.operator}</td></tr>
            <tr><td class="label">审批人:</td><td>{request.approver_email}</td></tr>
            <tr><td class="label">提交时间:</td><td>{current_time}</td></tr>
        </table>
        
        <p><strong>📎 报告PDF文件已作为附件随本邮件发送，请下载查看详细内容。</strong></p>
        
        <div class="buttons">
            <a href="{approve_url}" class="btn btn-approve">✅ 通过审批</a>
            <a href="{reject_url}" class="btn btn-reject">❌ 驳回报告</a>
        </div>
        
        <div class="warning">
            <strong>⚠️ 重要安全提示：</strong>
            <ul>
                <li><strong>本审批链接仅在公司局域网内有效</strong></li>
                <li>链接具有唯一性，仅能使用一次</li>
                <li>链接有效期为30分钟，过期后将自动失效</li>
                <li>请勿转发此邮件，链接仅限审批人本人使用</li>
                <li>点击审批按钮前会有二次确认，请仔细核对</li>
            </ul>
        </div>
        
        <p>如果上述按钮无法点击，请复制以下链接到浏览器地址栏：</p>
        <p><strong>通过审批：</strong><br><code>{approve_url}</code></p>
        <p><strong>驳回报告：</strong><br><code>{reject_url}</code></p>
    </div>
    
    <div class="footer">
        <p>本邮件由TianMu工业AGI试验台自动发送，请勿回复。</p>
        <p>如有技术问题，请联系系统管理员。</p>
        <p>服务器地址: {self.local_ip}:{self.port}</p>
    </div>
</body>
</html>
        '''
    
    def _generate_email_text(self, request: ApprovalRequest, 
                           approve_url: str, reject_url: str) -> str:
        """生成纯文本邮件内容"""
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
        
        return f'''
TianMu工业AGI试验台 - 实验报告审批通知

尊敬的审批人员，您好！

一份实验报告需要您的审批，具体信息如下：

报告编号: {request.report_id}
报告标题: {request.title}
操作员: {request.operator}
审批人: {request.approver_email}
提交时间: {current_time}

报告PDF文件已作为附件随本邮件发送，请下载查看详细内容。

请点击以下链接完成审批：

✅ 通过审批: {approve_url}
❌ 驳回报告: {reject_url}

⚠️ 重要安全提示：
• 本审批链接仅在公司局域网内有效
• 链接具有唯一性，仅能使用一次
• 链接有效期为30分钟，过期后将自动失效
• 请勿转发此邮件，链接仅限审批人本人使用
• 点击审批按钮前会有二次确认，请仔细核对

本邮件由TianMu工业AGI试验台自动发送，请勿回复。
如有技术问题，请联系系统管理员。

服务器地址: {self.local_ip}:{self.port}
        '''
    
    def _send_smtp_email(self, msg: MIMEMultipart, request: ApprovalRequest):
        """发送SMTP邮件"""
        if request.use_tls:
            context = ssl.create_default_context()
            server = smtplib.SMTP(request.smtp_server, request.smtp_port)
            server.starttls(context=context)
        else:
            server = smtplib.SMTP(request.smtp_server, request.smtp_port)
        
        server.login(request.from_email, request.email_password)
        text = msg.as_string()
        server.sendmail(request.from_email, request.approver_email, text)
        server.quit()

class ApprovalService:
    """审批服务主类"""
    
    def __init__(self, local_ip: str = "127.0.0.1", port: int = 8000):
        self.database = ApprovalDatabase()
        self.pdf_generator = PDFGenerator()
        self.email_sender = EmailSender(local_ip, port)
        logger.info("审批服务已初始化")
    
    def validate_internal_ip(self, ip_address: str) -> bool:
        """验证是否为局域网IP"""
        try:
            ip = ipaddress.ip_address(ip_address)
            return (
                ip.is_private or
                ip_address.startswith('192.168.') or
                ip_address.startswith('10.') or
                ip_address.startswith('172.') or
                ip_address == '127.0.0.1'
            )
        except ValueError:
            return False
    
    async def submit_approval_request(self, request: ApprovalRequest) -> Dict[str, Any]:
        """提交审批请求"""
        try:
            logger.info(f"收到审批请求 - ID: {request.report_id}")
            
            # 生成PDF报告
            pdf_path = self.pdf_generator.generate_report_pdf(request)
            logger.info(f"PDF报告已生成: {pdf_path}")
            
            # 生成唯一Token
            approve_token = str(uuid.uuid4())
            reject_token = str(uuid.uuid4())
            
            # 创建审批记录
            record = ApprovalRecord(
                id=str(uuid.uuid4()),
                report_id=request.report_id,
                title=request.title,
                content=request.content,
                operator=request.operator,
                approver_email=request.approver_email,
                approve_token=approve_token,
                reject_token=reject_token,
                status='pending',
                created_at=datetime.now(),
                pdf_path=str(pdf_path),
                client_ip=request.client_ip
            )
            
            # 保存记录
            if not self.database.save_record(record):
                return {
                    'success': False,
                    'message': '保存审批记录失败',
                    'report_id': request.report_id
                }
            
            # 发送审批邮件
            email_sent = self.email_sender.send_approval_email(
                request, approve_token, reject_token, pdf_path
            )
            
            if not email_sent:
                return {
                    'success': False,
                    'message': '发送审批邮件失败',
                    'report_id': request.report_id
                }
            
            # 记录操作日志
            self.database.log_action(
                request.report_id, 'submit', request.client_ip,
                details=f"审批请求已提交，邮件已发送至 {request.approver_email}"
            )
            
            logger.info(f"审批请求处理完成 - {request.report_id}")
            
            return {
                'success': True,
                'message': '审批请求已提交，邮件已发送',
                'report_id': request.report_id,
                'approval_id': record.id,
                'tokens_generated': True,
                'email_sent': True
            }
            
        except Exception as e:
            logger.error(f"提交审批请求失败: {e}")
            return {
                'success': False,
                'message': f'审批请求处理失败: {str(e)}',
                'report_id': request.report_id
            }
    
    def process_approval(self, token: str, token_type: str, action: str,
                        ip_address: str, user_agent: str, reason: str = None) -> Dict[str, Any]:
        """处理审批操作"""
        try:
            # 验证IP地址
            if not self.validate_internal_ip(ip_address):
                return {
                    'success': False,
                    'message': '仅允许局域网内访问',
                    'error_type': 'ip_restricted'
                }
            
            # 获取审批记录
            record = self.database.get_record_by_token(token, token_type)
            if not record:
                return {
                    'success': False,
                    'message': '无效的审批链接或链接已失效',
                    'error_type': 'invalid_token'
                }
            
            # 检查是否过期
            if record.is_expired():
                return {
                    'success': False,
                    'message': '审批链接已过期（有效期30分钟）',
                    'error_type': 'token_expired'
                }
            
            # 检查状态
            if record.status != 'pending':
                return {
                    'success': False,
                    'message': f'该报告已经被{record.status}，无法重复操作',
                    'error_type': 'already_processed'
                }
            
            # 更新审批记录
            success = self.database.update_record_status(
                token, token_type, action, ip_address, user_agent, reason
            )
            
            if not success:
                return {
                    'success': False,
                    'message': '更新审批状态失败',
                    'error_type': 'database_error'
                }
            
            # 记录操作日志
            self.database.log_action(
                record.report_id, action, ip_address, user_agent,
                details=f"审批结果: {action}" + (f", 原因: {reason}" if reason else "")
            )
            
            logger.info(f"审批操作完成 - {record.report_id}: {action}")
            
            return {
                'success': True,
                'message': f'审批{action}操作完成',
                'report_id': record.report_id,
                'action': action,
                'processed_at': datetime.now(),
                'record': record
            }
            
        except Exception as e:
            logger.error(f"处理审批操作失败: {e}")
            return {
                'success': False,
                'message': f'处理审批操作失败: {str(e)}',
                'error_type': 'system_error'
            }
    
    def get_approval_status(self, report_id: str) -> Dict[str, Any]:
        """查询审批状态"""
        try:
            with sqlite3.connect(self.database.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute('''
                    SELECT * FROM approval_records WHERE report_id = ?
                    ORDER BY created_at DESC LIMIT 1
                ''', (report_id,))
                
                row = cursor.fetchone()
                if not row:
                    return {
                        'success': False,
                        'message': '未找到审批记录'
                    }
                
                return {
                    'success': True,
                    'report_id': row['report_id'],
                    'status': row['status'],
                    'approver_email': row['approver_email'],
                    'created_at': row['created_at'],
                    'processed_at': row['processed_at'],
                    'reason': row['reason'],
                    'operator': row['operator'],
                    'title': row['title']
                }
                
        except Exception as e:
            logger.error(f"查询审批状态失败: {e}")
            return {
                'success': False,
                'message': f'查询失败: {str(e)}'
            }
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取审批统计信息"""
        try:
            with sqlite3.connect(self.database.db_path) as conn:
                cursor = conn.execute('''
                    SELECT 
                        COUNT(*) as total_reports,
                        SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending_approvals,
                        SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved_reports,
                        SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected_reports,
                        SUM(CASE WHEN date(created_at) = date('now') THEN 1 ELSE 0 END) as today_submissions
                    FROM approval_records
                ''')
                
                stats = cursor.fetchone()
                
                # 计算平均审批时间
                cursor = conn.execute('''
                    SELECT AVG(
                        (julianday(processed_at) - julianday(created_at)) * 24 * 60
                    ) as avg_approval_time_minutes
                    FROM approval_records 
                    WHERE processed_at IS NOT NULL AND status IN ('approved', 'rejected')
                ''')
                
                avg_time = cursor.fetchone()[0] or 0
                
                return {
                    'total_reports': stats[0],
                    'pending_approvals': stats[1],
                    'approved_reports': stats[2],
                    'rejected_reports': stats[3],
                    'today_submissions': stats[4],
                    'avg_approval_time_minutes': round(avg_time, 2)
                }
                
        except Exception as e:
            logger.error(f"获取审批统计失败: {e}")
            return {
                'total_reports': 0,
                'pending_approvals': 0,
                'approved_reports': 0,
                'rejected_reports': 0,
                'today_submissions': 0,
                'avg_approval_time_minutes': 0.0
            }