# app/routers/workload.py
"""
工况识别API路由 - 集成Qwen3 + LangChain + MCP
"""

import logging
import json
import asyncio
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

from app.services.workload_recognition_service import (
    get_workload_service, 
    LLMProvider, 
    TestType,
    WorkloadResult
)
from app.services.usage_tracker import track_usage_simple

logger = logging.getLogger(__name__)
router = APIRouter()

# 请求模型
class WorkloadTextRequest(BaseModel):
    """文本输入请求"""
    text: str
    language: str = "zh"
    llm_provider: Optional[str] = None  # "qwen", "cerebras", "auto"

class WorkloadOCRRequest(BaseModel):
    """OCR输入请求"""
    ocr_parameters: Dict[str, str]
    language: str = "zh"
    llm_provider: Optional[str] = None

class TestTypeConfirmRequest(BaseModel):
    """测试类型确认请求"""
    text: str
    confirmed_test_type: str
    language: str = "zh"
    llm_provider: Optional[str] = None

class LLMSwitchRequest(BaseModel):
    """LLM切换请求"""
    provider: str  # "qwen", "cerebras", "auto"

class PerformanceTestRequest(BaseModel):
    """性能测试请求"""
    test_text: str
    include_comparison: bool = True

# 响应模型
class TestTypeResponse(BaseModel):
    """测试类型响应"""
    detected_test_type: str
    confidence: str
    suggested_parameters: List[str]
    message: str
    processing_info: Dict[str, Any]

class ValidationResponse(BaseModel):
    """验证响应"""
    valid: bool
    standardized_parameters: Dict[str, Any]
    validation_errors: List[str]
    warnings: List[str]

class ServiceStatusResponse(BaseModel):
    """服务状态响应"""
    service: str
    version: str
    status: str
    components: Dict[str, str]
    supported_features: List[str]
    endpoints: List[str]
    current_llm: str
    available_llms: List[Dict[str, Any]]

# 工况识别API端点
@router.post("/recognize/text", response_model=WorkloadResult)
# @track_usage_simple("workload_text")
async def recognize_from_text(request: WorkloadTextRequest):
    """从文本识别工况 - 主要功能"""
    logger.info(f"[工况识别] 文本输入识别，长度: {len(request.text)}")
    
    try:
        # 选择LLM提供商
        llm_provider = None
        if request.llm_provider:
            try:
                llm_provider = LLMProvider(request.llm_provider)
            except ValueError:
                logger.warning(f"未知的LLM提供商: {request.llm_provider}，使用自动选择")
        
        service = get_workload_service()
        result = await service.recognize_from_text(
            request.text, 
            request.language,
            llm_provider
        )
        
        logger.info(f"[工况识别] 识别完成，测试类型: {result.test_type}, 阶段数: {result.total_stages}")
        return result
        
    except Exception as e:
        logger.error(f"[工况识别] 文本识别失败: {e}")
        raise HTTPException(500, f"工况识别失败: {str(e)}")

@router.post("/recognize/ocr", response_model=WorkloadResult)
# @track_usage_simple("workload_ocr")
async def recognize_from_ocr(request: WorkloadOCRRequest):
    """从OCR结果识别工况 - OCR集成功能"""
    logger.info(f"[工况识别] OCR输入识别，参数数量: {len(request.ocr_parameters)}")
    
    try:
        # 选择LLM提供商
        llm_provider = None
        if request.llm_provider:
            try:
                llm_provider = LLMProvider(request.llm_provider)
            except ValueError:
                logger.warning(f"未知的LLM提供商: {request.llm_provider}，使用自动选择")
        
        service = get_workload_service()
        result = await service.recognize_from_ocr(
            request.ocr_parameters, 
            request.language,
            llm_provider
        )
        
        logger.info(f"[工况识别] OCR识别完成，测试类型: {result.test_type}, 阶段数: {result.total_stages}")
        return result
        
    except Exception as e:
        logger.error(f"[工况识别] OCR识别失败: {e}")
        raise HTTPException(500, f"OCR工况识别失败: {str(e)}")

@router.post("/test-type/determine", response_model=TestTypeResponse)
# @track_usage_simple("workload_test_type")
async def determine_test_type(request: WorkloadTextRequest):
    """判断测试类型（两阶段处理的第一步）"""
    logger.info(f"[工况识别] 测试类型判断，输入长度: {len(request.text)}")
    
    try:
        # 选择LLM提供商
        llm_provider = None
        if request.llm_provider:
            try:
                llm_provider = LLMProvider(request.llm_provider)
            except ValueError:
                pass
        
        service = get_workload_service()
        
        # 使用内部方法判断测试类型
        start_time = datetime.now()
        test_type = await service._determine_test_type_with_llm(request.text, 
                                                              llm_provider or service._select_llm())
        processing_time = (datetime.now() - start_time).total_seconds()
        
        # 获取建议参数
        suggested_params = []
        if service.config:
            type_config = service.config.get_test_type_config(test_type.value)
            suggested_params = type_config.get("required_params", [])
        
        response = TestTypeResponse(
            detected_test_type=test_type.value,
            confidence="high" if test_type != TestType.UNKNOWN else "low",
            suggested_parameters=suggested_params,
            message=f"检测到测试类型：{test_type.value}，请确认是否正确？",
            processing_info={
                "llm_used": llm_provider.value if llm_provider else "auto",
                "processing_time": processing_time,
                "language": request.language
            }
        )
        
        logger.info(f"[工况识别] 测试类型判断完成: {test_type}")
        return response
        
    except Exception as e:
        logger.error(f"[工况识别] 测试类型判断失败: {e}")
        raise HTTPException(500, f"测试类型判断失败: {str(e)}")

@router.post("/recognize/confirmed", response_model=WorkloadResult)
# @track_usage_simple("workload_confirmed")
async def recognize_with_confirmed_type(request: TestTypeConfirmRequest):
    """用户确认测试类型后进行完整识别（两阶段处理的第二步）"""
    logger.info(f"[工况识别] 用户确认测试类型: {request.confirmed_test_type}")
    
    try:
        service = get_workload_service()
        
        # 将确认的测试类型映射到枚举
        type_mapping = {
            "耐久测试": TestType.ENDURANCE,
            "性能测试": TestType.PERFORMANCE,
        }
        
        confirmed_type = type_mapping.get(request.confirmed_test_type, TestType.UNKNOWN)
        if confirmed_type == TestType.UNKNOWN:
            raise HTTPException(400, f"不支持的测试类型: {request.confirmed_test_type}")
        
        # 选择LLM提供商
        llm_provider = None
        if request.llm_provider:
            try:
                llm_provider = LLMProvider(request.llm_provider)
            except ValueError:
                pass
        
        # 跳过类型判断，直接进行参数提取和处理
        start_time = datetime.now()
        
        # 提取参数
        extracted_params = await service._extract_parameters_with_llm(
            request.text, 
            llm_provider or service._select_llm()
        )
        
        # 标准化和校验
        standardized_params = await service._standardize_and_validate(extracted_params)
        
        # 生成阶段
        stages = await service._generate_stages(standardized_params)
        
        # 构建最终结果
        processing_time = (datetime.now() - start_time).total_seconds()
        result = await service._build_final_result(
            confirmed_type, 
            standardized_params, 
            stages,
            {
                "llm_used": llm_provider.value if llm_provider else "auto",
                "processing_time": processing_time,
                "language": request.language,
                "user_confirmed": True
            }
        )
        
        logger.info(f"[工况识别] 确认类型识别完成，阶段数: {result.total_stages}")
        return result
        
    except Exception as e:
        logger.error(f"[工况识别] 确认类型识别失败: {e}")
        raise HTTPException(500, f"确认类型识别失败: {str(e)}")

# LLM管理端点
@router.post("/llm/switch")
async def switch_llm_provider(request: LLMSwitchRequest):
    """切换LLM提供商"""
    logger.info(f"[工况识别] 切换LLM提供商: {request.provider}")
    
    try:
        # 验证提供商
        if request.provider not in ["qwen", "cerebras", "auto"]:
            raise HTTPException(400, f"不支持的LLM提供商: {request.provider}")
        
        service = get_workload_service()
        
        # 更新首选LLM
        if request.provider == "auto":
            service.preferred_llm = LLMProvider.AUTO
        elif request.provider == "qwen":
            service.preferred_llm = LLMProvider.QWEN
        elif request.provider == "cerebras":
            service.preferred_llm = LLMProvider.CEREBRAS
        
        # 测试新的LLM
        test_result = None
        if request.provider != "auto":
            try:
                selected_llm = LLMProvider(request.provider)
                if selected_llm in service.llm_services:
                    test_text = "测试消息"
                    test_result = await service._determine_test_type_with_llm(test_text, selected_llm)
                else:
                    raise Exception(f"LLM服务 {request.provider} 不可用")
            except Exception as e:
                logger.warning(f"LLM切换测试失败: {e}")
                test_result = f"测试失败: {str(e)}"
        
        return {
            "success": True,
            "current_provider": request.provider,
            "available_providers": [p.value for p in service.llm_services.keys() if isinstance(p, LLMProvider)],
            "test_result": str(test_result) if test_result else "未测试",
            "message": f"已切换到 {request.provider} LLM提供商"
        }
        
    except Exception as e:
        logger.error(f"[工况识别] LLM切换失败: {e}")
        raise HTTPException(500, f"LLM切换失败: {str(e)}")

@router.get("/llm/status")
async def get_llm_status():
    """获取LLM状态信息"""
    try:
        service = get_workload_service()
        status = service.get_service_status()
        
        return {
            "current_llm": service.preferred_llm.value,
            "available_llms": status["available_llms"],
            "total_count": status["total_llm_count"],
            "features": status["features"]
        }
        
    except Exception as e:
        logger.error(f"[工况识别] LLM状态获取失败: {e}")
        raise HTTPException(500, f"LLM状态获取失败: {str(e)}")

# 性能测试和比较端点
@router.post("/performance/compare")
async def compare_llm_performance(request: PerformanceTestRequest):
    """比较不同LLM的性能"""
    logger.info(f"[工况识别] LLM性能比较测试")
    
    try:
        service = get_workload_service()
        
        if request.include_comparison:
            comparison_result = await service.compare_llm_performance(request.test_text)
        else:
            comparison_result = {"message": "性能比较已禁用"}
        
        return {
            "test_text_length": len(request.test_text),
            "comparison_results": comparison_result,
            "available_llms": len(service.llm_services),
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"[工况识别] LLM性能比较失败: {e}")
        raise HTTPException(500, f"LLM性能比较失败: {str(e)}")

# 验证和工具端点
@router.post("/validate", response_model=ValidationResponse)
# @track_usage_simple("workload_validate")
async def validate_parameters(parameters: Dict[str, Any]):
    """验证参数的物理逻辑"""
    logger.info(f"[工况识别] 参数验证，参数数量: {len(parameters)}")
    
    try:
        service = get_workload_service()
        result = await service._standardize_and_validate(parameters)
        
        validation_result = result.get("validation_result", {})
        
        return ValidationResponse(
            valid=len(validation_result.get("errors", [])) == 0,
            standardized_parameters=result,
            validation_errors=validation_result.get("errors", []),
            warnings=validation_result.get("warnings", [])
        )
        
    except Exception as e:
        logger.error(f"[工况识别] 参数验证失败: {e}")
        raise HTTPException(500, f"参数验证失败: {str(e)}")

@router.get("/test-types")
async def get_supported_test_types():
    """获取支持的测试类型"""
    try:
        service = get_workload_service()
        
        # 获取支持的测试类型
        supported_types = []
        for test_type in TestType:
            if test_type != TestType.UNKNOWN:
                type_config = {}
                if service.config:
                    type_config = service.config.get_test_type_config(test_type.value)
                
                supported_types.append({
                    "code": test_type.name,
                    "name": test_type.value,
                    "required_params": type_config.get("required_params", []),
                    "tolerances": type_config.get("tolerances", {})
                })
        
        return {
            "supported_types": supported_types,
            "total_count": len(supported_types)
        }
        
    except Exception as e:
        logger.error(f"[工况识别] 获取测试类型失败: {e}")
        raise HTTPException(500, f"获取测试类型失败: {str(e)}")

# 状态和测试端点
@router.get("/status", response_model=ServiceStatusResponse)
async def get_service_status():
    """获取工况识别服务状态"""
    try:
        service = get_workload_service()
        status = service.get_service_status()
        
        # 检查各组件状态
        components_status = {
            "qwen3_llm": "可用" if LLMProvider.QWEN in service.llm_services else "未配置",
            "cerebras_llm": "可用" if LLMProvider.CEREBRAS in service.llm_services else "未配置",
            "mcp_server": "集成中",
            "langchain": "已集成",
            "ocr_integration": "已集成"
        }
        
        return ServiceStatusResponse(
            service="工况识别服务",
            version="2.1.0", 
            status="运行中",
            components=components_status,
            supported_features=[
                "自然语言工况识别",
                "OCR结果工况识别",
                "测试类型智能判断", 
                "多阶段自动生成",
                "物理参数校验",
                "单位自动转换",
                "多语言支持",
                "多LLM支持",
                "性能比较"
            ],
            endpoints=[
                "/workload/recognize/text - 文本工况识别",
                "/workload/recognize/ocr - OCR工况识别",
                "/workload/test-type/determine - 测试类型判断",
                "/workload/recognize/confirmed - 确认类型后识别",
                "/workload/llm/switch - 切换LLM提供商",
                "/workload/llm/status - LLM状态",
                "/workload/performance/compare - LLM性能比较",
                "/workload/validate - 参数验证",
                "/workload/test-types - 支持的测试类型",
                "/workload/status - 服务状态",
                "/workload/test - 服务测试"
            ],
            current_llm=service.preferred_llm.value,
            available_llms=status["available_llms"]
        )
        
    except Exception as e:
        logger.error(f"[工况识别] 状态检查失败: {e}")
        return ServiceStatusResponse(
            service="工况识别服务",
            version="2.1.0",
            status="错误",
            components={"error": str(e)},
            supported_features=[],
            endpoints=[],
            current_llm="unknown",
            available_llms=[]
        )

@router.get("/test")
async def test_workload_service():
    """测试工况识别服务"""
    test_text = """
    压缩机低温耐久测试
    吸气压力：0.1+-0.01Mpa（A）
    排气压力：1.0+-0.02Mpa（A）
    电压：650+-5V
    过热度：10±1°C
    过冷度：5°C
    转速：800±50rmp
    环温：-20℃±1°C
    低温：-40°C+-1°C
    高温：常温°C
    温度变化速率：1°C/min
    低温停留时间：7200min
    工作模式：产品在-20℃环境下开启，以1℃/min的变换速率调节至-40℃.保持120h后再以1℃/min的变化速率恢复至常温。
    """
    
    try:
        service = get_workload_service()
        
        # 执行基本测试
        start_time = datetime.now()
        result = await service.recognize_from_text(test_text)
        processing_time = (datetime.now() - start_time).total_seconds()
        
        return {
            "test_status": "成功",
            "processing_time": processing_time,
            "test_result": {
                "test_type": result.test_type.value,
                "total_stages": result.total_stages,
                "stage_count": len(result.stages),
                "has_validation_errors": len(result.validation_errors) > 0,
                "validation_errors": result.validation_errors
            },
            "service_info": {
                "current_llm": service.preferred_llm.value,
                "available_llms": len(service.llm_services)
            }
        }
        
    except Exception as e:
        logger.error(f"[工况识别] 测试失败: {e}")
        return {
            "test_status": "失败",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }