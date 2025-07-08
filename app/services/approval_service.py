# app/services/approval_service.py - 修复第二轮邮件发送版本
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
import pymysql
from pymysql.cursors import DictCursor

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT

logger = logging.getLogger(__name__)

@dataclass
class ApprovalRequest:
    """审批请求数据模型 - 支持两轮审批"""
    report_id: str
    title: str
    content: str
    operator: str
    first_approver_email: str  # 第一轮审批人邮箱
    second_approver_email: str  # 第二轮审批人邮箱
    smtp_server: str
    smtp_port: int
    from_email: str
    email_password: str
    use_tls: bool = True
    client_ip: str = "unknown"
    
@dataclass
class ApprovalRecord:
    """审批记录数据模型"""
    id: int
    report_id: str
    first_approver_email: str
    second_approver_email: str
    current_stage: int
    token: str
    status: str  # pending, approved, rejected, expired, cancelled, superseded, archived
    created_at: datetime
    approved_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    processor_ip: Optional[str] = None
    user_agent: Optional[str] = None
    reason: Optional[str] = None
    
    # 动态属性
    title: str = ""
    operator: str = ""
    
    @property
    def approver_email(self) -> str:
        """获取当前阶段的审批人邮箱"""
        if self.current_stage == 1:
            return self.first_approver_email
        else:
            return self.second_approver_email
    
    def is_expired(self) -> bool:
        """检查是否已过期（已取消时间限制）"""
        return False  # 取消时间限制

class ApprovalDatabase:
    """审批数据库管理 - MySQL版本"""
    
    def __init__(self, mysql_config: Dict[str, Any] = None):
        self.config = mysql_config or {
            'host': 'localhost',
            'port': 3306,
            'user': 'root',
            'password': 'tianmu008',
            'database': 'testdata'
        }
        self._test_connection()
        logger.info("MySQL审批数据库已连接")
    
    def _test_connection(self):
        """测试数据库连接"""
        try:
            conn = pymysql.connect(**self.config, cursorclass=DictCursor)
            conn.close()
            logger.info("MySQL数据库连接测试成功")
        except Exception as e:
            logger.error(f"MySQL数据库连接失败: {e}")
            raise
    
    def test_connection(self) -> bool:
        """测试数据库连接状态"""
        try:
            conn = pymysql.connect(**self.config, cursorclass=DictCursor)
            conn.close()
            return True
        except Exception as e:
            logger.error(f"数据库连接测试失败: {e}")
            return False
    
    def save_approval(self, report_id: str, first_approver: str, second_approver: str, 
                     token: str, current_stage: int = 1) -> Optional[int]:
        """保存审批记录"""
        try:
            conn = pymysql.connect(**self.config, cursorclass=DictCursor)
            try:
                with conn.cursor() as cursor:
                    sql = """
                        INSERT INTO approvals 
                        (ReportID, FirstApproverEmail, SecondApproverEmail, CurrentStage, Token, Status, CreatedAt)
                        VALUES (%s, %s, %s, %s, %s, 'pending', NOW())
                    """
                    cursor.execute(sql, (report_id, first_approver, second_approver, current_stage, token))
                    approval_id = cursor.lastrowid
                    conn.commit()
                    logger.info(f"审批记录已保存: ID={approval_id}, ReportID={report_id}")
                    return approval_id
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"保存审批记录失败: {e}")
            return None
    
    def get_approval_by_token(self, token: str) -> Optional[ApprovalRecord]:
        """根据token获取审批记录"""
        try:
            conn = pymysql.connect(**self.config, cursorclass=DictCursor)
            try:
                with conn.cursor() as cursor:
                    sql = """
                        SELECT a.*, r.Title, r.Submitter as operator
                        FROM approvals a
                        LEFT JOIN reports r ON a.ReportID = r.ReportID
                        WHERE a.Token = %s AND a.Status = 'pending'
                    """
                    cursor.execute(sql, (token,))
                    row = cursor.fetchone()
                    
                    if not row:
                        return None
                    
                    record = ApprovalRecord(
                        id=row['ID'],
                        report_id=row['ReportID'],
                        first_approver_email=row['FirstApproverEmail'],
                        second_approver_email=row['SecondApproverEmail'],
                        current_stage=row['CurrentStage'],
                        token=row['Token'],
                        status=row['Status'],
                        created_at=row['CreatedAt'],
                        approved_at=row['ApprovedAt'],
                        expires_at=row['ExpiresAt'],
                        processor_ip=row['ProcessorIP'],
                        user_agent=row['UserAgent'],
                        reason=row['Reason']
                    )
                    
                    # 设置动态属性
                    record.title = row.get('Title', '') or ''
                    record.operator = row.get('operator', '') or ''
                    
                    return record
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"查询审批记录失败: {e}")
            return None
    
    def get_original_smtp_config(self, report_id: str) -> Optional[Dict[str, Any]]:
        """获取原始提交时的SMTP配置信息"""
        try:
            conn = pymysql.connect(**self.config, cursorclass=DictCursor)
            try:
                with conn.cursor() as cursor:
                    # 从审批记录中获取SMTP配置信息（如果存储了的话）
                    # 这里我们需要一个新的方法来存储SMTP配置
                    # 暂时返回默认配置，实际使用时需要从提交时保存的配置中获取
                    return {
                        'smtp_server': 'smtp.qq.com',  # 需要从实际配置获取
                        'smtp_port': 587,
                        'from_email': 'system@tianmu.com',  # 需要从实际配置获取
                        'email_password': '',  # 需要从实际配置获取
                        'use_tls': True
                    }
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"获取SMTP配置失败: {e}")
            return None
    
    def update_approval_status(self, token: str, status: str, processor_ip: str, 
                              user_agent: str, reason: str = None, 
                              next_stage: int = None) -> bool:
        """更新审批记录状态"""
        try:
            conn = pymysql.connect(**self.config, cursorclass=DictCursor)
            try:
                with conn.cursor() as cursor:
                    if next_stage:
                        # 进入下一阶段
                        sql = """
                            UPDATE approvals 
                            SET CurrentStage = %s, ProcessorIP = %s, UserAgent = %s, Reason = %s
                            WHERE Token = %s AND Status = 'pending'
                        """
                        cursor.execute(sql, (next_stage, processor_ip, user_agent, reason, token))
                    else:
                        # 完成审批
                        sql = """
                            UPDATE approvals 
                            SET Status = %s, ApprovedAt = NOW(), ProcessorIP = %s, 
                                UserAgent = %s, Reason = %s
                            WHERE Token = %s AND Status = 'pending'
                        """
                        cursor.execute(sql, (status, processor_ip, user_agent, reason, token))
                    
                    success = cursor.rowcount > 0
                    conn.commit()
                    
                    if success:
                        logger.info(f"审批状态已更新: Token={token[:8]}..., Status={status}")
                    
                    return success
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"更新审批状态失败: {e}")
            return False
    
    def update_report_status(self, report_id: str, status: str) -> bool:
        """更新报告状态"""
        try:
            conn = pymysql.connect(**self.config, cursorclass=DictCursor)
            try:
                with conn.cursor() as cursor:
                    sql = "UPDATE reports SET Status = %s, UpdatedAt = NOW() WHERE ReportID = %s"
                    cursor.execute(sql, (status, report_id))
                    success = cursor.rowcount > 0
                    conn.commit()
                    
                    if success:
                        logger.info(f"报告状态已更新: {report_id} -> {status}")
                    
                    return success
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"更新报告状态失败: {e}")
            return False
    
    def log_approval_action(self, approval_id: int, action: str, ip_address: str, 
                           user_agent: str = None):
        """记录审批操作日志"""
        try:
            conn = pymysql.connect(**self.config, cursorclass=DictCursor)
            try:
                with conn.cursor() as cursor:
                    sql = """
                        INSERT INTO approval_logs 
                        (ApprovalID, Action, IPAddress, UserAgent, Timestamp)
                        VALUES (%s, %s, %s, %s, NOW())
                    """
                    cursor.execute(sql, (approval_id, action, ip_address, user_agent))
                    conn.commit()
                    logger.info(f"审批日志已记录: ApprovalID={approval_id}, Action={action}")
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"记录审批日志失败: {e}")

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
            ['第一轮审批人:', request.first_approver_email],
            ['第二轮审批人:', request.second_approver_email],
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

# 更新 EmailSender 类使用模板文件
from jinja2 import Environment, FileSystemLoader
import uuid
from pathlib import Path

class EmailSender:
    """邮件发送器 - 使用模板文件"""
    
    def __init__(self, local_ip: str = "127.0.0.1", port: int = 8000):
        self.local_ip = local_ip
        self.port = port
        
        # 初始化Jinja2模板环境
        template_dir = Path("app/templates")
        if not template_dir.exists():
            template_dir.mkdir(parents=True, exist_ok=True)
            logger.warning(f"模板目录不存在，已创建: {template_dir}")
        
        self.jinja_env = Environment(loader=FileSystemLoader(str(template_dir)))
        
        # 检查模板文件是否存在
        template_file = template_dir / "approval_email_templates.html"
        if not template_file.exists():
            logger.warning(f"邮件模板文件不存在: {template_file}")
            self._create_default_template(template_file)
    
    def _create_default_template(self, template_path: Path):
        """创建默认邮件模板文件"""
        default_template = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>实验报告审批通知</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; }
        .header { background: #007bff; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }
        .content { background: #f8f9fa; padding: 30px; border-radius: 0 0 8px 8px; }
        .btn { display: inline-block; padding: 15px 30px; margin: 0 10px; text-decoration: none; border-radius: 5px; font-weight: bold; }
        .btn-approve { background: #28a745; color: white; }
        .btn-reject { background: #dc3545; color: white; }
        .warning { background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; margin: 20px 0; border-radius: 5px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔬 实验报告审批通知</h1>
        <p>TianMu工业AGI试验台 · {{ stage_text }}审批</p>
    </div>
    <div class="content">
        <p>尊敬的审批人员，您好！</p>
        <p>一份实验报告需要您的{{ stage_text }}审批：</p>
        <ul>
            <li><strong>报告编号:</strong> {{ report_id }}</li>
            <li><strong>标题:</strong> {{ title }}</li>
            <li><strong>操作员:</strong> {{ operator }}</li>
            <li><strong>审批阶段:</strong> {{ stage_text }}</li>
            <li><strong>提交时间:</strong> {{ submit_time }}</li>
        </ul>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{{ approve_url }}" class="btn btn-approve">✅ 通过审批</a>
            <a href="{{ reject_url }}" class="btn btn-reject">❌ 驳回报告</a>
        </div>
        <div class="warning">
            <strong>⚠️ 重要提示：</strong>
            <ul>
                <li>本审批链接仅在公司局域网内有效</li>
                <li>链接无时间限制（已取消30分钟限制）</li>
                <li>请勿转发此邮件</li>
                <li>{{ stage_text }}审批{{ "通过后将自动进入第二轮审批" if stage_text == "第一轮" else "通过后报告将被最终批准" }}</li>
            </ul>
        </div>
    </div>
</body>
</html>'''
        
        try:
            with open(template_path, 'w', encoding='utf-8') as f:
                f.write(default_template)
            logger.info(f"已创建默认邮件模板: {template_path}")
        except Exception as e:
            logger.error(f"创建默认模板失败: {e}")
    
    def send_approval_email(self, request: ApprovalRequest, token: str, 
                          pdf_path: Path, stage: int = 1) -> bool:
        """发送审批邮件"""
        try:
            # 确定当前阶段的审批人
            approver_email = request.first_approver_email if stage == 1 else request.second_approver_email
            stage_text = f"第{stage}轮"
            
            # 创建邮件
            msg = MIMEMultipart('alternative')
            msg['From'] = request.from_email
            msg['To'] = approver_email
            msg['Subject'] = f"🔬 实验报告{stage_text}审批 - {request.title} ({request.report_id})"
            
            # 生成审批链接
            approve_url = f"http://{self.local_ip}:{self.port}/approval/approve?token={token}"
            reject_url = f"http://{self.local_ip}:{self.port}/approval/reject?token={token}"
            
            # 准备模板变量
            template_vars = {
                'report_id': request.report_id,
                'title': request.title,
                'operator': request.operator,
                'approver_email': approver_email,
                'content': request.content,
                'approve_url': approve_url,
                'reject_url': reject_url,
                'stage_text': stage_text,
                'submit_time': datetime.now().strftime("%Y年%m月%d日 %H:%M:%S"),
                'server_address': f"{self.local_ip}:{self.port}",
                'email_id': str(uuid.uuid4())[:8],
                'send_timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
            # 渲染HTML模板
            try:
                template = self.jinja_env.get_template('approval_email_templates.html')
                html_content = template.render(**template_vars)
            except Exception as e:
                logger.warning(f"使用模板失败，使用默认HTML: {e}")
                html_content = self._generate_fallback_html(request, approve_url, reject_url, stage_text)
            
            # 生成纯文本内容
            text_content = self._generate_email_text(request, approve_url, reject_url, stage_text)
            
            # 添加邮件内容
            part1 = MIMEText(text_content, 'plain', 'utf-8')
            part2 = MIMEText(html_content, 'html', 'utf-8')
            
            msg.attach(part1)
            msg.attach(part2)
            
            # 添加PDF附件
            if pdf_path and pdf_path.exists():
                with open(pdf_path, "rb") as attachment:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment.read())
                
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename= "report_{request.report_id}.pdf"'
                )
                msg.attach(part)
                logger.info(f"已添加PDF附件: {pdf_path}")
            else:
                logger.warning(f"PDF文件不存在或路径为空: {pdf_path}")
            
            # 发送邮件
            self._send_smtp_email(msg, request)
            logger.info(f"{stage_text}审批邮件发送成功: {approver_email}")
            return True
            
        except Exception as e:
            logger.error(f"发送审批邮件失败: {e}")
            return False
    
    def _generate_fallback_html(self, request: ApprovalRequest, 
                               approve_url: str, reject_url: str, stage_text: str) -> str:
        """生成备用HTML邮件内容"""
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
        
        return f'''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #007bff; color: white; padding: 20px; text-align: center; }}
        .content {{ padding: 20px; background: #f8f9fa; }}
        .btn {{ display: inline-block; padding: 15px 30px; margin: 10px; text-decoration: none; border-radius: 5px; font-weight: bold; }}
        .btn-approve {{ background: #28a745; color: white; }}
        .btn-reject {{ background: #dc3545; color: white; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🔬 实验报告{stage_text}审批通知</h1>
    </div>
    <div class="content">
        <p>尊敬的审批人员，您好！</p>
        <p>报告编号: <strong>{request.report_id}</strong></p>
        <p>报告标题: {request.title}</p>
        <p>操作员: {request.operator}</p>
        <p>审批阶段: {stage_text}</p>
        <p>提交时间: {current_time}</p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{approve_url}" class="btn btn-approve">✅ 通过审批</a>
            <a href="{reject_url}" class="btn btn-reject">❌ 驳回报告</a>
        </div>
        <p><strong>⚠️ 重要提示：</strong></p>
        <ul>
            <li>本审批链接仅在公司局域网内有效</li>
            <li>链接无时间限制（已取消30分钟限制）</li>
            <li>请勿转发此邮件</li>
        </ul>
    </div>
</body>
</html>
        '''
    
    def _generate_email_text(self, request: ApprovalRequest, 
                           approve_url: str, reject_url: str, stage_text: str) -> str:
        """生成纯文本邮件内容"""
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
        
        return f'''
TianMu工业AGI试验台 - 实验报告{stage_text}审批通知

尊敬的审批人员，您好！

一份实验报告需要您的{stage_text}审批，具体信息如下：

报告编号: {request.report_id}
报告标题: {request.title}
操作员: {request.operator}
审批阶段: {stage_text}
提交时间: {current_time}

报告PDF文件已作为附件随本邮件发送，请下载查看详细内容。

请点击以下链接完成审批：

✅ 通过审批: {approve_url}
❌ 驳回报告: {reject_url}

⚠️ 重要安全提示：
• 本审批链接仅在公司局域网内有效
• 链接具有唯一性，仅能使用一次
• 链接无时间限制（已取消30分钟限制）
• 请勿转发此邮件，链接仅限审批人本人使用

本邮件由TianMu工业AGI试验台自动发送，请勿回复。
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
        server.sendmail(request.from_email, msg['To'], text)
        server.quit()
        logger.info(f"SMTP邮件发送完成: {request.smtp_server}")

class ApprovalService:
    """审批服务主类 - 支持两轮审批的MySQL版本"""
    
    def __init__(self, local_ip: str = "127.0.0.1", port: int = 8000, 
                 mysql_config: Dict[str, Any] = None):
        default_config = {
            'host': 'localhost',
            'port': 3306,
            'user': 'root',
            'password': 'tianmu008',
            'database': 'testdata'
        }
        # 使用传入的配置或默认配置
        final_config = mysql_config or default_config
        
        self.database = ApprovalDatabase(final_config)
        self.pdf_generator = PDFGenerator()
        self.email_sender = EmailSender(local_ip, port)
        
        # 存储最近的SMTP配置，用于第二轮邮件发送
        self._last_smtp_config = None
        
        logger.info("两轮审批服务已初始化 (MySQL)")
    
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
        """提交两轮审批请求"""
        try:
            logger.info(f"收到两轮审批请求 - ID: {request.report_id}")
            
            # 保存SMTP配置供后续使用
            self._last_smtp_config = {
                'smtp_server': request.smtp_server,
                'smtp_port': request.smtp_port,
                'from_email': request.from_email,
                'email_password': request.email_password,
                'use_tls': request.use_tls
            }
            logger.info(f"已保存SMTP配置供第二轮使用: {request.smtp_server}")
            
            # 生成PDF报告
            pdf_path = self.pdf_generator.generate_report_pdf(request)
            logger.info(f"PDF报告已生成: {pdf_path}")
            
            # 生成唯一Token（用于第一轮审批）
            token = str(uuid.uuid4())
            
            # 保存审批记录
            approval_id = self.database.save_approval(
                request.report_id, 
                request.first_approver_email, 
                request.second_approver_email, 
                token,
                current_stage=1
            )
            
            if not approval_id:
                return {
                    'success': False,
                    'message': '保存审批记录失败',
                    'report_id': request.report_id
                }
            
            # 更新报告状态为审批中
            self.database.update_report_status(request.report_id, 'InReview')
            
            # 发送第一轮审批邮件
            email_sent = self.email_sender.send_approval_email(
                request, token, pdf_path, stage=1
            )
            
            if not email_sent:
                return {
                    'success': False,
                    'message': '发送第一轮审批邮件失败',
                    'report_id': request.report_id
                }
            
            # 记录操作日志
            self.database.log_approval_action(
                approval_id, 'submit', request.client_ip
            )
            
            logger.info(f"两轮审批请求处理完成 - {request.report_id}")
            
            return {
                'success': True,
                'message': '第一轮审批请求已提交，邮件已发送',
                'report_id': request.report_id,
                'approval_id': approval_id,
                'current_stage': 1,
                'tokens_generated': True,
                'email_sent': True
            }
            
        except Exception as e:
            logger.error(f"提交两轮审批请求失败: {e}")
            return {
                'success': False,
                'message': f'审批请求处理失败: {str(e)}',
                'report_id': request.report_id
            }
    
    def process_approval(self, token: str, action: str, new_status: str,
                        ip_address: str, user_agent: str, reason: str = None) -> Dict[str, Any]:
        """处理审批操作（支持两轮审批）"""
        try:
            # 验证IP地址
            if not self.validate_internal_ip(ip_address):
                return {
                    'success': False,
                    'message': '仅允许局域网内访问',
                    'error_type': 'ip_restricted'
                }
            
            # 获取审批记录
            record = self.database.get_approval_by_token(token)
            if not record:
                return {
                    'success': False,
                    'message': '无效的审批链接或链接已失效',
                    'error_type': 'invalid_token'
                }
            
            # 检查状态
            if record.status != 'pending':
                return {
                    'success': False,
                    'message': f'该报告已经被{record.status}，无法重复操作',
                    'error_type': 'already_processed'
                }
            
            # 记录操作日志
            self.database.log_approval_action(
                record.id, action, ip_address, user_agent
            )
            
            if action == 'approve':
                # 审批通过
                if record.current_stage == 1:
                    # 第一轮审批通过，启动第二轮
                    return self._handle_first_stage_approval(record, ip_address, user_agent, reason)
                else:
                    # 第二轮审批通过，最终批准
                    return self._handle_second_stage_approval(record, ip_address, user_agent, reason)
            
            elif action == 'reject':
                # 审批驳回
                return self._handle_rejection(record, ip_address, user_agent, reason)
            
            else:
                return {
                    'success': False,
                    'message': '未知的审批操作',
                    'error_type': 'invalid_action'
                }
            
        except Exception as e:
            logger.error(f"处理审批操作失败: {e}")
            return {
                'success': False,
                'message': f'处理审批操作失败: {str(e)}',
                'error_type': 'system_error'
            }
    
    def _handle_first_stage_approval(self, record: ApprovalRecord, ip_address: str, 
                                   user_agent: str, reason: str = None) -> Dict[str, Any]:
        """处理第一轮审批通过"""
        try:
            # 生成第二轮审批的新Token
            new_token = str(uuid.uuid4())
            
            # 更新第一轮审批记录为已完成
            success = self.database.update_approval_status(
                record.token, 'approved', ip_address, user_agent, reason
            )
            
            if not success:
                return {
                    'success': False,
                    'message': '更新第一轮审批状态失败',
                    'error_type': 'database_error'
                }
            
            # 创建第二轮审批记录
            approval_id = self.database.save_approval(
                record.report_id,
                record.first_approver_email,
                record.second_approver_email,
                new_token,
                current_stage=2
            )
            
            if not approval_id:
                return {
                    'success': False,
                    'message': '创建第二轮审批记录失败',
                    'error_type': 'database_error'
                }
            
            # 更新报告状态
            self.database.update_report_status(record.report_id, 'InApproval')
            
            # 发送第二轮审批邮件（关键修复）
            try:
                # 检查是否有保存的SMTP配置
                if not self._last_smtp_config:
                    logger.warning("没有找到SMTP配置，使用默认配置")
                    self._last_smtp_config = {
                        'smtp_server': 'smtp.qq.com',
                        'smtp_port': 587,
                        'from_email': 'system@tianmu.com',
                        'email_password': 'your_password_here',  # 需要实际密码
                        'use_tls': True
                    }
                
                # 重新构造请求对象用于发送邮件（使用保存的SMTP配置）
                second_stage_request = ApprovalRequest(
                    report_id=record.report_id,
                    title=record.title,
                    content="第二轮审批阶段，详情请查看附件PDF文件",
                    operator=record.operator,
                    first_approver_email=record.first_approver_email,
                    second_approver_email=record.second_approver_email,
                    smtp_server=self._last_smtp_config['smtp_server'],
                    smtp_port=self._last_smtp_config['smtp_port'],
                    from_email=self._last_smtp_config['from_email'],
                    email_password=self._last_smtp_config['email_password'],
                    use_tls=self._last_smtp_config['use_tls']
                )
                
                # 查找已生成的PDF文件
                pdf_path = None
                pdf_search_pattern = f"report_{record.report_id}_*.pdf"
                existing_pdfs = list(Path("Data/approval/reports").glob(pdf_search_pattern))
                
                if existing_pdfs:
                    # 使用最新的PDF文件
                    pdf_path = sorted(existing_pdfs, key=lambda x: x.stat().st_mtime)[-1]
                    logger.info(f"找到现有PDF文件: {pdf_path}")
                else:
                    # 如果没有找到PDF，重新生成
                    logger.warning("未找到现有PDF文件，重新生成")
                    pdf_path = self.pdf_generator.generate_report_pdf(second_stage_request)
                
                # 发送第二轮审批邮件
                email_sent = self.email_sender.send_approval_email(
                    second_stage_request, new_token, pdf_path, stage=2
                )
                
                if email_sent:
                    logger.info(f"✅ 第二轮审批邮件发送成功: {record.second_approver_email}")
                else:
                    logger.error(f"❌ 第二轮审批邮件发送失败: {record.second_approver_email}")
                
            except Exception as e:
                logger.error(f"❌ 发送第二轮审批邮件时发生异常: {e}")
                # 即使邮件发送失败，也不影响审批流程继续
            
            logger.info(f"第一轮审批通过，已启动第二轮 - {record.report_id}")
            
            return {
                'success': True,
                'message': '第一轮审批通过，第二轮审批已启动',
                'report_id': record.report_id,
                'stage': 1,
                'next_action': 'start_second_stage',
                'record': record,
                'second_stage_token': new_token  # 返回第二轮token供调试
            }
            
        except Exception as e:
            logger.error(f"处理第一轮审批失败: {e}")
            return {
                'success': False,
                'message': f'处理第一轮审批失败: {str(e)}',
                'error_type': 'system_error'
            }
    
    def _handle_second_stage_approval(self, record: ApprovalRecord, ip_address: str, 
                                    user_agent: str, reason: str = None) -> Dict[str, Any]:
        """处理第二轮审批通过"""
        try:
            # 更新审批状态为最终批准
            success = self.database.update_approval_status(
                record.token, 'approved', ip_address, user_agent, reason
            )
            
            if not success:
                return {
                    'success': False,
                    'message': '更新审批状态失败',
                    'error_type': 'database_error'
                }
            
            # 更新报告状态为最终批准
            self.database.update_report_status(record.report_id, 'Approved')
            
            logger.info(f"第二轮审批通过，报告最终批准 - {record.report_id}")
            
            return {
                'success': True,
                'message': '第二轮审批通过，报告已最终批准',
                'report_id': record.report_id,
                'stage': 2,
                'next_action': 'final_approved',
                'record': record
            }
            
        except Exception as e:
            logger.error(f"处理第二轮审批失败: {e}")
            return {
                'success': False,
                'message': f'处理第二轮审批失败: {str(e)}',
                'error_type': 'system_error'
            }
    
    def _handle_rejection(self, record: ApprovalRecord, ip_address: str, 
                         user_agent: str, reason: str = None) -> Dict[str, Any]:
        """处理审批驳回"""
        try:
            # 更新审批状态为驳回
            success = self.database.update_approval_status(
                record.token, 'rejected', ip_address, user_agent, reason
            )
            
            if not success:
                return {
                    'success': False,
                    'message': '更新审批状态失败',
                    'error_type': 'database_error'
                }
            
            # 根据阶段更新报告状态
            if record.current_stage == 1:
                # 第一轮驳回
                self.database.update_report_status(record.report_id, 'ReviewRejected')
            else:
                # 第二轮驳回
                self.database.update_report_status(record.report_id, 'Rejected')
            
            logger.info(f"第{record.current_stage}轮审批驳回 - {record.report_id}")
            
            return {
                'success': True,
                'message': f'第{record.current_stage}轮审批已驳回',
                'report_id': record.report_id,
                'stage': record.current_stage,
                'next_action': 'rejected',
                'record': record
            }
            
        except Exception as e:
            logger.error(f"处理审批驳回失败: {e}")
            return {
                'success': False,
                'message': f'处理审批驳回失败: {str(e)}',
                'error_type': 'system_error'
            }
    
    def get_approval_status(self, report_id: str) -> Dict[str, Any]:
        """查询审批状态"""
        try:
            conn = pymysql.connect(**self.database.config, cursorclass=DictCursor)
            try:
                with conn.cursor() as cursor:
                    sql = """
                        SELECT a.*, r.Title, r.Submitter, r.Status as ReportStatus
                        FROM approvals a
                        LEFT JOIN reports r ON a.ReportID = r.ReportID
                        WHERE a.ReportID = %s
                        ORDER BY a.CreatedAt DESC LIMIT 1
                    """
                    cursor.execute(sql, (report_id,))
                    row = cursor.fetchone()
                    
                    if not row:
                        return {
                            'success': False,
                            'message': '未找到审批记录'
                        }
                    
                    return {
                        'success': True,
                        'report_id': row['ReportID'],
                        'status': row['Status'],
                        'current_stage': row['CurrentStage'],
                        'first_approver_email': row['FirstApproverEmail'],
                        'second_approver_email': row['SecondApproverEmail'],
                        'created_at': row['CreatedAt'].isoformat() if row['CreatedAt'] else None,
                        'approved_at': row['ApprovedAt'].isoformat() if row['ApprovedAt'] else None,
                        'reason': row['Reason'],
                        'title': row['Title'],
                        'submitter': row['Submitter'],
                        'report_status': row['ReportStatus']
                    }
            finally:
                conn.close()
                
        except Exception as e:
            logger.error(f"查询审批状态失败: {e}")
            return {
                'success': False,
                'message': f'查询失败: {str(e)}'
            }
    
    async def get_approval_statistics(self) -> Dict[str, Any]:
        """获取审批统计信息"""
        try:
            conn = pymysql.connect(**self.database.config, cursorclass=DictCursor)
            try:
                with conn.cursor() as cursor:
                    # 基础统计
                    cursor.execute("""
                        SELECT 
                            COUNT(*) as total_reports,
                            SUM(CASE WHEN Status = 'pending' THEN 1 ELSE 0 END) as pending_approvals,
                            SUM(CASE WHEN Status = 'approved' THEN 1 ELSE 0 END) as approved_reports,
                            SUM(CASE WHEN Status = 'rejected' THEN 1 ELSE 0 END) as rejected_reports,
                            SUM(CASE WHEN DATE(CreatedAt) = CURDATE() THEN 1 ELSE 0 END) as today_submissions
                        FROM approvals
                    """)
                    
                    stats = cursor.fetchone()
                    
                    # 计算平均审批时间
                    cursor.execute("""
                        SELECT AVG(TIMESTAMPDIFF(MINUTE, CreatedAt, ApprovedAt)) as avg_approval_time_minutes
                        FROM approvals 
                        WHERE ApprovedAt IS NOT NULL AND Status IN ('approved', 'rejected')
                    """)
                    
                    avg_time_result = cursor.fetchone()
                    avg_time = avg_time_result['avg_approval_time_minutes'] if avg_time_result else 0
                    
                    # 阶段统计
                    cursor.execute("""
                        SELECT 
                            CurrentStage,
                            COUNT(*) as count,
                            Status
                        FROM approvals
                        GROUP BY CurrentStage, Status
                    """)
                    
                    stage_results = cursor.fetchall()
                    stage_statistics = {}
                    for row in stage_results:
                        stage = f"stage_{row['CurrentStage']}"
                        if stage not in stage_statistics:
                            stage_statistics[stage] = {}
                        stage_statistics[stage][row['Status']] = row['count']
                    
                    return {
                        'total_reports': stats['total_reports'],
                        'pending_approvals': stats['pending_approvals'],
                        'approved_reports': stats['approved_reports'],
                        'rejected_reports': stats['rejected_reports'],
                        'today_submissions': stats['today_submissions'],
                        'avg_approval_time_minutes': round(float(avg_time or 0), 2),
                        'stage_statistics': stage_statistics
                    }
            finally:
                conn.close()
                
        except Exception as e:
            logger.error(f"获取审批统计失败: {e}")
            return {
                'total_reports': 0,
                'pending_approvals': 0,
                'approved_reports': 0,
                'rejected_reports': 0,
                'today_submissions': 0,
                'avg_approval_time_minutes': 0.0,
                'stage_statistics': {}
            }  
              
    async def _ensure_cache_initialized(self):
        """确保缓存已初始化（兼容性方法）"""
        pass
    
    def set_smtp_config(self, smtp_config: Dict[str, Any]):
        """手动设置SMTP配置供第二轮邮件使用"""
        self._last_smtp_config = smtp_config
        logger.info(f"手动设置SMTP配置: {smtp_config.get('smtp_server', 'unknown')}")
    
    def get_last_smtp_config(self) -> Optional[Dict[str, Any]]:
        """获取最后使用的SMTP配置"""
        return self._last_smtp_config