# app/routers/approval.py - 重新设计的审批路由
from fastapi import APIRouter, HTTPException, Request, Form, Query, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, validator
from typing import Optional
import logging
import socket
from datetime import datetime

from app.services.approval_service import ApprovalService, ApprovalRequest
from app.services.usage_tracker import track_usage_simple

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/approval", tags=["实验审批系统"])

# 模板引擎
templates = Jinja2Templates(directory="app/templates")

# 审批服务实例
approval_service = None

def get_approval_service():
    """获取审批服务实例"""
    global approval_service
    if approval_service is None:
        # 获取本机IP地址
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            if local_ip.startswith('127.'):
                # 尝试获取实际局域网IP
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                local_ip = s.getsockname()[0]
                s.close()
        except:
            local_ip = "127.0.0.1"
        
        approval_service = ApprovalService(local_ip=local_ip, port=8000)
        logger.info(f"审批服务已初始化 - 服务器地址: {local_ip}:8000")
    
    return approval_service

class SubmitReportRequest(BaseModel):
    """提交报告请求模型"""
    report_id: str
    title: str
    content: str
    operator: str
    approver_email: EmailStr
    
    # SMTP配置
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

def validate_internal_ip(request: Request) -> bool:
    """验证请求IP是否为内网地址"""
    client_ip = request.client.host
    if not client_ip:
        return False
    
    service = get_approval_service()
    return service.validate_internal_ip(client_ip)

@router.post("/submit_report")
@track_usage_simple("approval_submit")
async def submit_report(request: Request, report_data: SubmitReportRequest):
    """
    上位机提交实验报告审批请求
    
    功能：
    1. 接收上位机的审批请求
    2. 生成PDF报告
    3. 创建审批Token
    4. 发送审批邮件
    """
    logger.info(f"收到报告审批请求 - ID: {report_data.report_id}")
    
    try:
        # 验证请求来源
        if not validate_internal_ip(request):
            logger.warning(f"非内网请求被拒绝 - IP: {request.client.host}")
            raise HTTPException(
                status_code=403, 
                detail="仅允许内网访问"
            )
        
        # 创建审批请求
        approval_request = ApprovalRequest(
            report_id=report_data.report_id,
            title=report_data.title,
            content=report_data.content,
            operator=report_data.operator,
            approver_email=report_data.approver_email,
            smtp_server=report_data.smtp_server,
            smtp_port=report_data.smtp_port,
            from_email=report_data.from_email,
            email_password=report_data.email_password,
            use_tls=report_data.use_tls,
            client_ip=request.client.host
        )
        
        # 提交审批请求
        service = get_approval_service()
        result = await service.submit_approval_request(approval_request)
        
        if result['success']:
            logger.info(f"审批请求处理成功 - {report_data.report_id}")
            return JSONResponse(content=result)
        else:
            logger.error(f"审批请求处理失败 - {report_data.report_id}: {result['message']}")
            raise HTTPException(
                status_code=500,
                detail=result['message']
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提交审批请求失败: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"审批请求处理失败: {str(e)}"
        )

@router.get("/approve", response_class=HTMLResponse)
async def approve_report(
    request: Request,
    token: str = Query(..., description="审批Token"),
    confirm: Optional[str] = Query(None, description="确认参数")
):
    """
    处理审批通过请求
    
    流程：
    1. 验证内网访问
    2. 验证Token有效性
    3. 显示确认页面或处理审批
    """
    logger.info(f"收到审批通过请求 - Token: {token[:8]}...")
    
    try:
        # 验证内网访问
        if not validate_internal_ip(request):
            return templates.TemplateResponse(
                "approval_error.html",
                {
                    "request": request,
                    "error": "访问被拒绝",
                    "message": "该审批链接仅在公司局域网内有效",
                    "client_ip": request.client.host
                }
            )
        
        service = get_approval_service()
        
        # 如果没有确认参数，先验证token并显示确认页面
        if confirm != 'yes':
            # 获取审批记录用于显示确认页面
            record = service.database.get_record_by_token(token, 'approve')
            
            if not record:
                return templates.TemplateResponse(
                    "approval_error.html",
                    {
                        "request": request,
                        "error": "无效的审批链接",
                        "message": "该链接已失效或不存在"
                    }
                )
            
            if record.is_expired():
                return templates.TemplateResponse(
                    "approval_error.html",
                    {
                        "request": request,
                        "error": "链接已过期",
                        "message": "该审批链接已超过有效期（30分钟）"
                    }
                )
            
            if record.status != 'pending':
                return templates.TemplateResponse(
                    "approval_error.html",
                    {
                        "request": request,
                        "error": "审批已完成",
                        "message": f"该报告已经被{record.status}，无法重复操作"
                    }
                )
            
            # 显示确认页面
            return templates.TemplateResponse(
                "approval_confirm.html",
                {
                    "request": request,
                    "approval": record,
                    "action": "approve",
                    "action_text": "通过",
                    "confirm_url": f"/approval/approve?token={token}&confirm=yes"
                }
            )
        
        # 执行审批通过
        result = service.process_approval(
            token, 'approve', 'approved',
            request.client.host,
            request.headers.get('user-agent', '')
        )
        
        if result['success']:
            logger.info(f"报告审批通过 - {result['report_id']}")
            return templates.TemplateResponse(
                "approval_success.html",
                {
                    "request": request,
                    "approval": result['record'],
                    "action": "通过",
                    "message": "实验报告审批已通过"
                }
            )
        else:
            return templates.TemplateResponse(
                "approval_error.html",
                {
                    "request": request,
                    "error": "审批失败",
                    "message": result['message']
                }
            )
        
    except Exception as e:
        logger.error(f"审批通过处理失败: {str(e)}")
        return templates.TemplateResponse(
            "approval_error.html",
            {
                "request": request,
                "error": "系统错误",
                "message": f"处理审批时发生错误: {str(e)}"
            }
        )

@router.get("/reject", response_class=HTMLResponse)
async def reject_report(
    request: Request,
    token: str = Query(..., description="驳回Token"),
    confirm: Optional[str] = Query(None, description="确认参数")
):
    """
    处理审批驳回请求（显示确认页面）
    """
    logger.info(f"收到审批驳回请求 - Token: {token[:8]}...")
    
    try:
        # 验证内网访问
        if not validate_internal_ip(request):
            return templates.TemplateResponse(
                "approval_error.html",
                {
                    "request": request,
                    "error": "访问被拒绝",
                    "message": "该审批链接仅在公司局域网内有效",
                    "client_ip": request.client.host
                }
            )
        
        service = get_approval_service()
        
        # 验证Token
        record = service.database.get_record_by_token(token, 'reject')
        
        if not record:
            return templates.TemplateResponse(
                "approval_error.html",
                {
                    "request": request,
                    "error": "无效的审批链接",
                    "message": "该链接已失效或不存在"
                }
            )
        
        if record.is_expired():
            return templates.TemplateResponse(
                "approval_error.html",
                {
                    "request": request,
                    "error": "链接已过期",
                    "message": "该审批链接已超过有效期（30分钟）"
                }
            )
        
        if record.status != 'pending':
            return templates.TemplateResponse(
                "approval_error.html",
                {
                    "request": request,
                    "error": "审批已完成",
                    "message": f"该报告已经被{record.status}，无法重复操作"
                }
            )
        
        # 显示驳回确认页面（包含原因输入）
        return templates.TemplateResponse(
            "approval_reject_confirm.html",
            {
                "request": request,
                "approval": record,
                "action": "reject",
                "action_text": "驳回",
                "token": token
            }
        )
        
    except Exception as e:
        logger.error(f"审批驳回处理失败: {str(e)}")
        return templates.TemplateResponse(
            "approval_error.html",
            {
                "request": request,
                "error": "系统错误",
                "message": f"处理审批时发生错误: {str(e)}"
            }
        )

@router.post("/reject", response_class=HTMLResponse)
async def reject_report_with_reason(
    request: Request,
    token: str = Form(..., description="驳回Token"),
    reason: str = Form(..., description="驳回原因")
):
    """处理带原因的审批驳回"""
    logger.info(f"收到审批驳回确认 - Token: {token[:8]}...")
    
    try:
        # 验证内网访问
        if not validate_internal_ip(request):
            return templates.TemplateResponse(
                "approval_error.html",
                {
                    "request": request,
                    "error": "访问被拒绝",
                    "message": "该审批链接仅在公司局域网内有效"
                }
            )
        
        # 验证驳回原因
        if not reason or len(reason.strip()) < 10:
            return templates.TemplateResponse(
                "approval_error.html",
                {
                    "request": request,
                    "error": "驳回原因无效",
                    "message": "请提供详细的驳回原因（至少10个字符）"
                }
            )
        
        service = get_approval_service()
        
        # 执行审批驳回
        result = service.process_approval(
            token, 'reject', 'rejected',
            request.client.host,
            request.headers.get('user-agent', ''),
            reason.strip()
        )
        
        if result['success']:
            logger.info(f"报告审批驳回 - {result['report_id']}")
            return templates.TemplateResponse(
                "approval_success.html",
                {
                    "request": request,
                    "approval": result['record'],
                    "action": "驳回",
                    "message": f"实验报告审批已驳回，原因：{reason}"
                }
            )
        else:
            return templates.TemplateResponse(
                "approval_error.html",
                {
                    "request": request,
                    "error": "驳回失败",
                    "message": result['message']
                }
            )
        
    except Exception as e:
        logger.error(f"审批驳回处理失败: {str(e)}")
        return templates.TemplateResponse(
            "approval_error.html",
            {
                "request": request,
                "error": "系统错误",
                "message": f"处理审批时发生错误: {str(e)}"
            }
        )

@router.get("/status/{report_id}")
async def get_approval_status(
    request: Request,
    report_id: str
):
    """
    查询审批状态
    供上位机查询使用
    """
    try:
        # 验证内网访问
        if not validate_internal_ip(request):
            raise HTTPException(status_code=403, detail="仅允许内网访问")
        
        service = get_approval_service()
        result = service.get_approval_status(report_id)
        
        if result['success']:
            return result
        else:
            raise HTTPException(status_code=404, detail=result['message'])
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"查询审批状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")

@router.get("/statistics")
async def get_approval_statistics(request: Request):
    """获取审批统计信息"""
    try:
        # 验证内网访问
        if not validate_internal_ip(request):
            raise HTTPException(status_code=403, detail="仅允许内网访问")
        
        service = get_approval_service()
        stats = service.get_statistics()
        
        return {
            "success": True,
            "statistics": stats,
            "timestamp": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取审批统计失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}")

@router.get("/test")
async def test_approval_system():
    """测试审批系统状态"""
    try:
        service = get_approval_service()
        
        return {
            "status": "OPERATIONAL",
            "service": "Experiment Approval System",
            "version": "2.0.0",
            "features": [
                "实验报告PDF生成",
                "邮件审批流程",
                "局域网安全验证",
                "一次性Token机制",
                "审批记录追溯"
            ],
            "endpoints": [
                "/approval/submit_report - 提交审批请求",
                "/approval/approve - 审批通过",
                "/approval/reject - 审批驳回",
                "/approval/status/{report_id} - 查询状态",
                "/approval/statistics - 获取统计",
                "/approval/test - 系统测试"
            ],
            "security": {
                "internal_network_only": True,
                "token_expiry_minutes": 30,
                "one_time_use_tokens": True,
                "ip_validation": True
            },
            "database_status": "connected",
            "pdf_generator_status": "ready",
            "email_service_status": "ready"
        }
        
    except Exception as e:
        logger.error(f"审批系统测试失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"系统异常: {str(e)}")

# API路由，供管理后台调用
@router.get("/api/stats")
async def get_approval_stats_api(request: Request):
    """获取审批系统统计信息（API接口）"""
    try:
        service = get_approval_service()
        stats = service.get_statistics()
        
        return {
            "total_reports": stats["total_reports"],
            "pending_approvals": stats["pending_approvals"],
            "approved_reports": stats["approved_reports"],
            "rejected_reports": stats["rejected_reports"],
            "today_submissions": stats["today_submissions"],
            "avg_approval_time_minutes": stats["avg_approval_time_minutes"],
            "system_status": "OPERATIONAL",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"获取审批统计API失败: {str(e)}")
        return {
            "system_status": "ERROR",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }