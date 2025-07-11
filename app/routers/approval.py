# app/routers/approval.py - 两轮审批版本（修复版）
from fastapi import APIRouter, HTTPException, Request, Form, Query, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr, validator
from typing import Optional
import logging
import socket
from datetime import datetime, timedelta
from pathlib import Path

from app.services.approval_service import ApprovalService, ApprovalRequest

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
        
        # MySQL数据库配置（修复版）
        mysql_config = {
            'host': 'localhost',
            'port': 3306,
            'user': 'root',
            'password': 'tianmu008',
            'database': 'testdata'
        }
        
        approval_service = ApprovalService(
            local_ip=local_ip, 
            port=8000, 
            mysql_config=mysql_config
        )
        logger.info(f"两轮审批服务已初始化 - 服务器地址: {local_ip}:8000, 数据库: MySQL")
    
    return approval_service

class SubmitReportRequest(BaseModel):
    """提交报告请求模型 - 支持两轮审批"""
    report_id: str
    title: str
    content: str
    operator: str
    first_approver_email: EmailStr  # 第一轮审批人邮箱
    second_approver_email: EmailStr  # 第二轮审批人邮箱
    
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
async def submit_report(request: Request, report_data: SubmitReportRequest):
    """
    上位机提交实验报告审批请求（两轮审批）
    """
    logger.info(f"收到两轮审批请求 - ID: {report_data.report_id}")
    
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
            first_approver_email=report_data.first_approver_email,
            second_approver_email=report_data.second_approver_email,
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
            logger.info(f"两轮审批请求处理成功 - {report_data.report_id}")
            return JSONResponse(content=result)
        else:
            logger.error(f"两轮审批请求处理失败 - {report_data.report_id}: {result['message']}")
            raise HTTPException(
                status_code=500,
                detail=result['message']
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"提交两轮审批请求失败: {str(e)}")
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
    """处理审批通过请求"""
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
            record = service.database.get_approval_by_token(token)
            
            if not record:
                return templates.TemplateResponse(
                    "approval_error.html",
                    {
                        "request": request,
                        "error": "无效的审批链接",
                        "message": "该链接已失效或不存在"
                    }
                )
            
            # 取消时间限制检查
            # if record.is_expired():
            #     return templates.TemplateResponse(
            #         "approval_error.html",
            #         {
            #             "request": request,
            #             "error": "链接已过期",
            #             "message": "该审批链接已超过有效期"
            #         }
            #     )
            
            if record.status != 'pending':
                return templates.TemplateResponse(
                    "approval_error.html",
                    {
                        "request": request,
                        "error": "审批已完成",
                        "message": f"该报告已经被{record.status}，无法重复操作"
                    }
                )
            
            # 添加审批阶段信息
            stage_text = f"第{record.current_stage}轮" if record.current_stage else ""
            
            # 显示确认页面
            return templates.TemplateResponse(
                "approval_confirm.html",
                {
                    "request": request,
                    "approval": record,
                    "action": "approve",
                    "action_text": "通过",
                    "stage_text": stage_text,
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
            stage_text = f"第{result.get('stage', '')}轮" if result.get('stage') else ""
            next_action = result.get('next_action', '')
            
            # 根据下一步动作设置不同的消息
            if next_action == 'start_second_stage':
                message = f"{stage_text}审批已通过，第二轮审批邮件已发送"
            elif next_action == 'final_approved':
                message = f"{stage_text}审批已通过，报告最终批准"
            else:
                message = f"{stage_text}审批已通过"
            
            logger.info(f"报告{stage_text}审批通过 - {result['report_id']}")
            return templates.TemplateResponse(
                "approval_success.html",
                {
                    "request": request,
                    "approval": result['record'],
                    "action": "通过",
                    "stage_text": stage_text,
                    "message": message,
                    "next_action": next_action
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
    """处理审批驳回请求（显示确认页面）"""
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
        record = service.database.get_approval_by_token(token)
        
        if not record:
            return templates.TemplateResponse(
                "approval_error.html",
                {
                    "request": request,
                    "error": "无效的审批链接",
                    "message": "该链接已失效或不存在"
                }
            )
        
        # 取消时间限制检查
        # if record.is_expired():
        #     return templates.TemplateResponse(
        #         "approval_error.html",
        #         {
        #             "request": request,
        #             "error": "链接已过期",
        #             "message": "该审批链接已超过有效期"
        #         }
        #     )
        
        if record.status != 'pending':
            return templates.TemplateResponse(
                "approval_error.html",
                {
                    "request": request,
                    "error": "审批已完成",
                    "message": f"该报告已经被{record.status}，无法重复操作"
                }
            )
        
        # 添加审批阶段信息
        stage_text = f"第{record.current_stage}轮" if record.current_stage else ""
        
        # 显示驳回确认页面（包含原因输入）
        return templates.TemplateResponse(
            "approval_reject_confirm.html",
            {
                "request": request,
                "approval": record,
                "action": "reject",
                "action_text": "驳回",
                "stage_text": stage_text,
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
            stage_text = f"第{result.get('stage', '')}轮" if result.get('stage') else ""
            logger.info(f"报告{stage_text}审批驳回 - {result['report_id']}")
            return templates.TemplateResponse(
                "approval_success.html",
                {
                    "request": request,
                    "approval": result['record'],
                    "action": "驳回",
                    "stage_text": stage_text,
                    "message": f"{stage_text}审批已驳回，原因：{reason}"
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
    """查询审批状态"""
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
        stats = await service.get_approval_statistics()
        
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
        
        # 测试数据库连接
        db_status = service.database.test_connection()
        
        return {
            "status": "OPERATIONAL" if db_status else "DATABASE_ERROR",
            "service": "Two-Stage Experiment Approval System",
            "version": "2.2.0 MySQL TwoStage Fixed",
            "database": {
                "type": "MySQL",
                "host": service.database.config['host'],
                "port": service.database.config['port'],
                "database": service.database.config['database'],
                "connection_status": "OK" if db_status else "FAILED"
            },
            "approval_stages": {
                "first_stage": "第一轮审批 - 技术审核",
                "second_stage": "第二轮审批 - 管理审批",
                "auto_progression": "第一轮通过后自动启动第二轮"
            },
            "fixes_applied": [
                "取消30分钟时间限制",
                "修复数据库连接配置",
                "优化两轮审批流程",
                "修复邮件模板问题",
                "改进错误处理机制"
            ],
            "features": [
                "两轮审批流程",
                "自动邮件转发",
                "reports表状态同步",
                "MySQL数据库存储",
                "审批记录追溯",
                "操作日志记录",
                "无时间限制审批链接"
            ],
            "endpoints": [
                "/approval/submit_report - 提交两轮审批请求",
                "/approval/approve - 审批通过",
                "/approval/reject - 审批驳回",
                "/approval/status/{report_id} - 查询状态",
                "/approval/statistics - 获取统计",
                "/approval/test - 系统测试"
            ],
            "security": {
                "internal_network_only": True,
                "token_expiry": "无限制（已取消30分钟限制）",
                "one_time_use_tokens": True,
                "ip_validation": True,
                "database_logging": True
            },
            "report_status_flow": [
                "InReview -> (第一轮审批) -> InApproval -> (第二轮审批) -> Approved",
                "InReview -> (第一轮驳回) -> ReviewRejected",
                "InApproval -> (第二轮驳回) -> Rejected"
            ],
            "email_template": "approval_email_templates.html",
            "time_limit_removed": True
        }
        
    except Exception as e:
        logger.error(f"审批系统测试失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"系统异常: {str(e)}")

@router.get("/api/stats")
async def get_approval_stats_api(request: Request):
    """获取审批系统统计信息（API接口）"""
    try:
        service = get_approval_service()
        stats = await service.get_approval_statistics()
        
        return {
            "total_reports": stats["total_reports"],
            "pending_approvals": stats["pending_approvals"],
            "approved_reports": stats["approved_reports"],
            "rejected_reports": stats["rejected_reports"],
            "today_submissions": stats["today_submissions"],
            "avg_approval_time_minutes": stats["avg_approval_time_minutes"],
            "stage_statistics": stats.get("stage_statistics", {}),
            "system_status": "OPERATIONAL",
            "database_type": "MySQL",
            "approval_type": "Two-Stage",
            "time_limit_removed": True,
            "version": "2.2.0-FIXED",
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"获取审批统计API失败: {str(e)}")
        return {
            "system_status": "ERROR",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }