# app/services/email_sender.py - 邮件发送服务
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import Dict, Any, Optional
import logging
from datetime import datetime
import socket
import asyncio

logger = logging.getLogger(__name__)

class EmailSender:
    """邮件发送服务"""
    
    def __init__(self):
        # 获取本机IP地址（用于生成审批链接）
        self.local_ip = self._get_local_ip()
        self.server_port = 8000  # FastAPI服务端口
        
        logger.info(f"邮件发送服务已初始化，服务地址: {self.local_ip}:{self.server_port}")
    
    def _get_local_ip(self) -> str:
        """获取本机局域网IP地址"""
        try:
            # 创建一个UDP socket连接来获取本机IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            # 如果获取失败，返回默认值
            return "192.168.1.100"
    
    async def send_approval_email(
        self,
        to_email: str,
        report_id: str,
        title: str,
        operator: str,
        approve_token: str,
        reject_token: str,
        pdf_path: Path,
        smtp_config: Dict[str, Any]
    ) -> bool:
        """
        发送审批邮件
        
        Args:
            to_email: 收件人邮箱
            report_id: 报告ID
            title: 报告标题
            operator: 操作员
            approve_token: 审批通过Token
            reject_token: 审批驳回Token
            pdf_path: PDF文件路径
            smtp_config: SMTP配置
        
        Returns:
            发送是否成功
        """
        try:
            logger.info(f"开始发送审批邮件到: {to_email}")
            
            # 创建邮件对象
            msg = MIMEMultipart('alternative')
            msg['From'] = smtp_config['username']
            msg['To'] = to_email
            msg['Subject'] = f"实验报告审批 - {title} ({report_id})"
            
            # 生成审批链接
            base_url = f"http://{self.local_ip}:{self.server_port}"
            approve_url = f"{base_url}/approval/approve?token={approve_token}"
            reject_url = f"{base_url}/approval/reject?token={reject_token}"
            
            # 生成邮件内容
            html_content = self._generate_email_html(
                report_id=report_id,
                title=title,
                operator=operator,
                to_email=to_email,
                approve_url=approve_url,
                reject_url=reject_url
            )
            
            text_content = self._generate_email_text(
                report_id=report_id,
                title=title,
                operator=operator,
                to_email=to_email,
                approve_url=approve_url,
                reject_url=reject_url
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
                    f'attachment; filename= "report_{report_id}.pdf"',
                )
                msg.attach(part)
                logger.info(f"已添加PDF附件: {pdf_path}")
            else:
                logger.warning(f"PDF文件不存在: {pdf_path}")
            
            # 发送邮件
            await self._send_email(msg, smtp_config)
            
            logger.info(f"审批邮件发送成功: {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"发送审批邮件失败: {e}")
            return False
    
    def _generate_email_html(
        self,
        report_id: str,
        title: str,
        operator: str,
        to_email: str,
        approve_url: str,
        reject_url: str
    ) -> str:
        """生成HTML邮件内容"""
        
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
        
        html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>实验报告审批</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f4f4f4;
        }}
        .container {{
            background-color: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
        }}
        .header {{
            text-align: center;
            border-bottom: 2px solid #007bff;
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}
        .header h1 {{
            color: #007bff;
            margin: 0;
            font-size: 24px;
        }}
        .info-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }}
        .info-table td {{
            padding: 10px;
            border: 1px solid #ddd;
        }}
        .info-table .label {{
            background-color: #f8f9fa;
            font-weight: bold;
            width: 120px;
        }}
        .buttons {{
            text-align: center;
            margin: 30px 0;
        }}
        .btn {{
            display: inline-block;
            padding: 15px 30px;
            margin: 0 10px;
            text-decoration: none;
            border-radius: 5px;
            font-weight: bold;
            font-size: 16px;
            transition: all 0.3s ease;
        }}
        .btn-approve {{
            background-color: #28a745;
            color: white;
        }}
        .btn-approve:hover {{
            background-color: #218838;
        }}
        .btn-reject {{
            background-color: #dc3545;
            color: white;
        }}
        .btn-reject:hover {{
            background-color: #c82333;
        }}
        .warning {{
            background-color: #fff3cd;
            border: 1px solid #ffeaa7;
            padding: 15px;
            border-radius: 5px;
            margin: 20px 0;
        }}
        .warning h3 {{
            margin-top: 0;
            color: #856404;
        }}
        .warning ul {{
            margin: 10px 0;
            padding-left: 20px;
        }}
        .footer {{
            text-align: center;
            font-size: 12px;
            color: #666;
            border-top: 1px solid #ddd;
            padding-top: 20px;
            margin-top: 30px;
        }}
        .highlight {{
            background-color: #e7f3ff;
            padding: 2px 4px;
            border-radius: 3px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔬 实验报告审批通知</h1>
            <p>TianMu工业AGI试验台 · 审批系统</p>
        </div>
        
        <p>尊敬的审批人员，您好！</p>
        
        <p>一份实验报告需要您的审批，具体信息如下：</p>
        
        <table class="info-table">
            <tr>
                <td class="label">报告编号:</td>
                <td><span class="highlight">{report_id}</span></td>
            </tr>
            <tr>
                <td class="label">报告标题:</td>
                <td>{title}</td>
            </tr>
            <tr>
                <td class="label">操作员:</td>
                <td>{operator}</td>
            </tr>
            <tr>
                <td class="label">审批人邮箱:</td>
                <td>{to_email}</td>
            </tr>
            <tr>
                <td class="label">提交时间:</td>
                <td>{current_time}</td>
            </tr>
        </table>
        
        <p><strong>📎 报告PDF文件已作为附件随本邮件发送，请下载查看详细内容。</strong></p>
        
        <div class="buttons">
            <a href="{approve_url}" class="btn btn-approve">✅ 通过审批</a>
            <a href="{reject_url}" class="btn btn-reject">❌ 驳回报告</a>
        </div>
        
        <div class="warning">
            <h3>⚠️ 重要安全提示</h3>
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
        
        <div class="footer">
            <p>本邮件由TianMu工业AGI试验台自动发送，请勿回复。</p>
            <p>如有技术问题，请联系系统管理员。</p>
            <p>服务器地址: {self.local_ip}:{self.server_port}</p>
        </div>
    </div>
</body>
</html>
        """
        
        return html_content
    
    def _generate_email_text(
        self,
        report_id: str,
        title: str,
        operator: str,
        to_email: str,
        approve_url: str,
        reject_url: str
    ) -> str:
        """生成纯文本邮件内容"""
        
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M:%S")
        
        text_content = f"""
TianMu工业AGI试验台 - 实验报告审批通知

尊敬的审批人员，您好！

一份实验报告需要您的审批，具体信息如下：

报告编号: {report_id}
报告标题: {title}
操作员: {operator}
审批人邮箱: {to_email}
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

服务器地址: {self.local_ip}:{self.server_port}
        """
        
        return text_content
    
    async def _send_email(self, msg: MIMEMultipart, smtp_config: Dict[str, Any]):
        """发送邮件到SMTP服务器"""
        try:
            # 创建SMTP连接
            if smtp_config.get('use_tls', True):
                # 使用TLS加密
                context = ssl.create_default_context()
                server = smtplib.SMTP(smtp_config['server'], smtp_config['port'])
                server.starttls(context=context)
            else:
                # 不使用加密
                server = smtplib.SMTP(smtp_config['server'], smtp_config['port'])
            
            # 登录
            server.login(smtp_config['username'], smtp_config['password'])
            
            # 发送邮件
            text = msg.as_string()
            server.sendmail(smtp_config['username'], msg['To'], text)
            
            # 关闭连接
            server.quit()
            
            logger.info(f"邮件发送成功到SMTP服务器: {smtp_config['server']}")
            
        except Exception as e:
            logger.error(f"SMTP邮件发送失败: {e}")
            raise
    
    async def send_notification_email(
        self,
        to_email: str,
        subject: str,
        content: str,
        smtp_config: Dict[str, Any],
        attachment_path: Optional[Path] = None
    ) -> bool:
        """
        发送通知邮件
        
        Args:
            to_email: 收件人邮箱
            subject: 邮件主题
            content: 邮件内容
            smtp_config: SMTP配置
            attachment_path: 附件路径（可选）
        
        Returns:
            发送是否成功
        """
        try:
            logger.info(f"开始发送通知邮件到: {to_email}")
            
            # 创建邮件对象
            msg = MIMEMultipart()
            msg['From'] = smtp_config['username']
            msg['To'] = to_email
            msg['Subject'] = subject
            
            # 添加邮件内容
            msg.attach(MIMEText(content, 'plain', 'utf-8'))
            
            # 添加附件（如果有）
            if attachment_path and attachment_path.exists():
                with open(attachment_path, "rb") as attachment:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment.read())
                
                encoders.encode_base64(part)
                part.add_header(
                    'Content-Disposition',
                    f'attachment; filename= "{attachment_path.name}"',
                )
                msg.attach(part)
                logger.info(f"已添加附件: {attachment_path}")
            
            # 发送邮件
            await self._send_email(msg, smtp_config)
            
            logger.info(f"通知邮件发送成功: {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"发送通知邮件失败: {e}")
            return False
    
    def test_smtp_connection(self, smtp_config: Dict[str, Any]) -> bool:
        """
        测试SMTP连接
        
        Args:
            smtp_config: SMTP配置
        
        Returns:
            连接是否成功
        """
        try:
            logger.info(f"测试SMTP连接: {smtp_config['server']}:{smtp_config['port']}")
            
            # 创建SMTP连接
            if smtp_config.get('use_tls', True):
                context = ssl.create_default_context()
                server = smtplib.SMTP(smtp_config['server'], smtp_config['port'], timeout=10)
                server.starttls(context=context)
            else:
                server = smtplib.SMTP(smtp_config['server'], smtp_config['port'], timeout=10)
            
            # 尝试登录
            server.login(smtp_config['username'], smtp_config['password'])
            
            # 关闭连接
            server.quit()
            
            logger.info("SMTP连接测试成功")
            return True
            
        except Exception as e:
            logger.error(f"SMTP连接测试失败: {e}")
            return False
    
    def get_server_info(self) -> Dict[str, Any]:
        """获取邮件服务信息"""
        return {
            "local_ip": self.local_ip,
            "server_port": self.server_port,
            "base_url": f"http://{self.local_ip}:{self.server_port}",
            "approval_endpoints": {
                "approve": f"http://{self.local_ip}:{self.server_port}/approval/approve",
                "reject": f"http://{self.local_ip}:{self.server_port}/approval/reject"
            }
        }