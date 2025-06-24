# app/routers/cerebras.py
"""
Cerebras API路由
"""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

from app.services.cerebras_service import (
    get_cerebras_service, 
    CerebrasMessage, 
    CerebrasResponse
)
from app.services.llm_factory import llm_factory
from app.services.usage_tracker import track_usage_simple

router = APIRouter()

class ChatRequest(BaseModel):
    """聊天请求模型"""
    messages: List[Dict[str, str]]
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

class SimplePromptRequest(BaseModel):
    """简单提示词请求"""
    prompt: str
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

@router.post("/chat/completions", response_model=CerebrasResponse)
@track_usage_simple("cerebras_chat")
async def cerebras_chat_completion(request: ChatRequest):
    """Cerebras聊天完成API"""
    service = get_cerebras_service()
    if not service:
        raise HTTPException(500, "Cerebras服务未配置或不可用")
    
    try:
        # 转换消息格式
        messages = [
            CerebrasMessage(role=msg["role"], content=msg["content"]) 
            for msg in request.messages
        ]
        
        response = await service.chat_completion(
            messages=messages,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens
        )
        
        return response
        
    except Exception as e:
        raise HTTPException(500, f"Cerebras API调用失败: {str(e)}")

@router.post("/simple")
# @track_usage_simple("cerebras_simple")  # 暂时注释掉
async def cerebras_simple_completion(request: SimplePromptRequest):
    """简单的文本完成"""
    service = get_cerebras_service()
    if not service:
        raise HTTPException(500, "Cerebras服务未配置或不可用")
    
    try:
        response_text = await service.simple_completion(
            prompt=request.prompt,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens
        )
        
        return {"response": response_text}
        
    except Exception as e:
        raise HTTPException(500, f"Cerebras简单完成失败: {str(e)}")

@router.get("/test")
async def test_cerebras():
    """测试Cerebras连接"""
    service = get_cerebras_service()
    if not service:
        return {
            "status": "not_configured",
            "message": "Cerebras服务未配置，请设置CEREBRAS_API_KEY环境变量"
        }
    
    test_result = await service.test_connection()
    return test_result

@router.get("/status")
async def cerebras_status():
    """获取Cerebras服务状态"""
    service = get_cerebras_service()
    if not service:
        return {
            "status": "not_available",
            "message": "Cerebras服务未配置"
        }
    
    return service.get_status()

@router.get("/models")
async def list_cerebras_models():
    """列出可用的Cerebras模型"""
    return {
        "models": [
            {
                "id": "llama3.1-8b",
                "name": "Llama 3.1 8B",
                "description": "高性能8B参数模型",
                "speed": "ultra-fast"
            },
            {
                "id": "llama3.1-70b", 
                "name": "Llama 3.1 70B",
                "description": "大型70B参数模型",
                "speed": "fast"
            }
        ],
        "default": "llama3.1-8b"
    }

@router.get("/compare-llms")
async def compare_all_llms():
    """比较所有可用的LLM提供商"""
    results = await llm_factory.test_all_providers()
    
    return {
        "available_providers": [p.value for p in llm_factory.get_available_providers()],
        "test_results": results,
        "recommendation": _get_llm_recommendation(results)
    }

def _get_llm_recommendation(test_results: Dict[str, Any]) -> Dict[str, str]:
    """根据测试结果推荐LLM"""
    recommendations = {}
    
    # 速度推荐
    cerebras_time = test_results.get("cerebras", {}).get("response_time", float('inf'))
    qwen_available = "qwen" in test_results
    
    if cerebras_time < 1.0:  # 1秒以下
        recommendations["speed"] = "cerebras - 超高速推理"
    elif qwen_available:
        recommendations["speed"] = "qwen - 平衡性能"
    else:
        recommendations["speed"] = "无高速选项可用"
    
    # 功能推荐
    if qwen_available:
        recommendations["features"] = "qwen - 完整功能支持"
    elif "cerebras" in test_results:
        recommendations["features"] = "cerebras - 高速推理"
    else:
        recommendations["features"] = "无推荐"
    
    return recommendations