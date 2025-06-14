# app/routers/approval.py - 实验审批系统路由
from fastapi import APIRouter, HTTPException, Request, Form, Query, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, EmailStr
from typing import Optional, Dict, Any
import logging
import ipaddress
from datetime import datetime, timedelta
import uuid
import os
from pathlib import Path

from app.services.approval_service import ApprovalService
from app.services.pdf_generator import PDFGenerator
from app.services.email_sender import EmailSender
from app.services.usage_tracker import track_usage_simple, ServiceType
from app.schemas.approval import (
    SubmitReportRequest, 
    SubmitReportResponse,
    ApprovalActionResponse
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/approval", tags=["实验审批系统"])

# 初始化服务
approval_service = ApprovalService()
pdf_generator = PDFGenerator()
email_sender = EmailSender()

# 模板引擎
templates = Jinja2Templates(directory="app/templates")

def validate_internal_ip(request: Request) -> bool:
    """验证请求IP是否为内网地址"""
    client_ip = request.client.host
    if not client_ip:
        return False
    
    try:
        ip = ipaddress.ip_address(client_ip)
        # 检查是否为私有网络地址
        return (
            ip.is_private or 
            client_ip.startswith('192.168.') or
            client_ip.startswith('10.') or
            client_ip.startswith('172.') or
            client_ip == '127.0.0.1'
        )
    except ValueError:
        return False

@router.post("/submit_report", response_model=SubmitReportResponse)
@track_usage_simple("approval_submit")
async def submit_report(
    request: Request,
    report_data: SubmitReportRequest
):
    """
    上位机提交实验报告审批请求
    
    功能：
    1. 接收上位机的审批请求
    2. 生成PDF报告
    3. 创建审批Token
    4. 发送审批邮件
    """
    logger.info(f"[APPROVAL] 收到报告审批请求 - ID: {report_data.report_id}")
    
    try:
        # 1. 验证请求来源
        if not validate_internal_ip(request):
            logger.warning(f"[APPROVAL] 非内网请求被拒绝 - IP: {request.client.host}")
            raise HTTPException(
                status_code=403, 
                detail="仅允许内网访问"
            )
        
        # 2. 生成PDF报告
        logger.info(f"[APPROVAL] 开始生成PDF报告 - {report_data.report_id}")
        pdf_path = await pdf_generator.generate_report_pdf(
            report_id=report_data.report_id,
            title=report_data.title,
            content=report_data.content,
            experiment_data=report_data.experiment_data,
            operator=report_data.operator
        )
        
        # 3. 创建审批记录和Token
        approval_record = await approval_service.create_approval_request(
            report_id=report_data.report_id,
            title=report_data.title,
            content=report_data.content,
            operator=report_data.operator,
            approver_email=report_data.approver_email,
            pdf_path=str(pdf_path),
            client_ip=request.client.host
        )
        
        # 4. 发送审批邮件
        logger.info(f"[APPROVAL] 发送审批邮件到: {report_data.approver_email}")
        await email_sender.send_approval_email(
            to_email=report_data.approver_email,
            report_id=report_data.report_id,
            title=report_data.title,
            operator=report_data.operator,
            approve_token=approval_record.approve_token,
            reject_token=approval_record.reject_token,
            pdf_path=pdf_path,
            smtp_config={
                'server': report_data.smtp_server,
                'port': report_data.smtp_port,
                'username': report_data.from_email,
                'password': report_data.email_password,
                'use_tls': report_data.use_tls
            }
        )
        
        logger.info(f"[APPROVAL] 审批请求处理完成 - {report_data.report_id}")
        
        return SubmitReportResponse(
            success=True,
            message="审批请求已提交，邮件已发送",
            report_id=report_data.report_id,
            approval_id=approval_record.id,
            tokens_generated=True,
            email_sent=True
        )
        
    except Exception as e:
        logger.error(f"[APPROVAL] 提交审批请求失败: {str(e)}")
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
    logger.info(f"[APPROVAL] 收到审批通过请求 - Token: {token[:8]}...")
    
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
        
        # 验证Token
        approval_record = await approval_service.get_approval_by_token(token, 'approve')
        
        if not approval_record:
            return templates.TemplateResponse(
                "approval_error.html",
                {
                    "request": request,
                    "error": "无效的审批链接",
                    "message": "该链接已失效或不存在"
                }
            )
        
        if approval_record.is_expired():
            return templates.TemplateResponse(
                "approval_error.html",
                {
                    "request": request,
                    "error": "链接已过期",
                    "message": "该审批链接已超过有效期（30分钟）"
                }
            )
        
        if approval_record.status != 'pending':
            return templates.TemplateResponse(
                "approval_error.html",
                {
                    "request": request,
                    "error": "审批已完成",
                    "message": f"该报告已经被{approval_record.status}，无法重复操作"
                }
            )
        
        # 如果没有确认参数，显示确认页面
        if confirm != 'yes':
            return templates.TemplateResponse(
                "approval_confirm.html",
                {
                    "request": request,
                    "approval": approval_record,
                    "action": "approve",
                    "action_text": "通过",
                    "confirm_url": f"/approval/approve?token={token}&confirm=yes"
                }
            )
        
        # 执行审批通过
        await approval_service.process_approval(
            approval_record,
            action='approved',
            ip_address=request.client.host,
            user_agent=request.headers.get('user-agent', '')
        )
        
        logger.info(f"[APPROVAL] 报告审批通过 - {approval_record.report_id}")
        
        return templates.TemplateResponse(
            "approval_success.html",
            {
                "request": request,
                "approval": approval_record,
                "action": "通过",
                "message": "实验报告审批已通过"
            }
        )
        
    except Exception as e:
        logger.error(f"[APPROVAL] 审批通过处理失败: {str(e)}")
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
    confirm: Optional[str] = Query(None, description="确认参数"),
    reason: Optional[str] = Form(None, description="驳回原因")
):
    """
    处理审批驳回请求
    """
    logger.info(f"[APPROVAL] 收到审批驳回请求 - Token: {token[:8]}...")
    
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
        
        # 验证Token
        approval_record = await approval_service.get_approval_by_token(token, 'reject')
        
        if not approval_record:
            return templates.TemplateResponse(
                "approval_error.html",
                {
                    "request": request,
                    "error": "无效的审批链接",
                    "message": "该链接已失效或不存在"
                }
            )
        
        if approval_record.is_expired():
            return templates.TemplateResponse(
                "approval_error.html",
                {
                    "request": request,
                    "error": "链接已过期",
                    "message": "该审批链接已超过有效期（30分钟）"
                }
            )
        
        if approval_record.status != 'pending':
            return templates.TemplateResponse(
                "approval_error.html",
                {
                    "request": request,
                    "error": "审批已完成",
                    "message": f"该报告已经被{approval_record.status}，无法重复操作"
                }
            )
        
        # 如果没有确认参数，显示确认页面
        if confirm != 'yes':
            return templates.TemplateResponse(
                "approval_reject_confirm.html",
                {
                    "request": request,
                    "approval": approval_record,
                    "action": "reject",
                    "action_text": "驳回",
                    "token": token
                }
            )
        
        # 执行审批驳回
        await approval_service.process_approval(
            approval_record,
            action='rejected',
            ip_address=request.client.host,
            user_agent=request.headers.get('user-agent', ''),
            reason=reason
        )
        
        logger.info(f"[APPROVAL] 报告审批驳回 - {approval_record.report_id}")
        
        return templates.TemplateResponse(
            "approval_success.html",
            {
                "request": request,
                "approval": approval_record,
                "action": "驳回",
                "message": f"实验报告审批已驳回{f'，原因：{reason}' if reason else ''}"
            }
        )
        
    except Exception as e:
        logger.error(f"[APPROVAL] 审批驳回处理失败: {str(e)}")
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
    return await reject_report(request, token, "yes", reason)

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
        
        approval_record = await approval_service.get_approval_by_report_id(report_id)
        
        if not approval_record:
            raise HTTPException(status_code=404, detail="未找到审批记录")
        
        return {
            "report_id": approval_record.report_id,
            "status": approval_record.status,
            "approver_email": approval_record.approver_email,
            "created_at": approval_record.created_at.isoformat(),
            "processed_at": approval_record.processed_at.isoformat() if approval_record.processed_at else None,
            "reason": approval_record.reason
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[APPROVAL] 查询审批状态失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")

@router.get("/test", tags=["实验审批系统"])
async def test_approval_system():
    """测试审批系统状态"""
    try:
        return {
            "status": "OPERATIONAL",
            "service": "Experiment Approval System",
            "version": "1.0.0",
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
                "/approval/test - 系统测试"
            ],
            "security": {
                "internal_network_only": True,
                "token_expiry_minutes": 30,
                "one_time_use_tokens": True,
                "ip_validation": True
            }
        }
        
    except Exception as e:
        logger.error(f"[APPROVAL] 审批系统测试失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"系统异常: {str(e)}")