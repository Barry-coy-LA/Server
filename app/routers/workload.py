# app/routers/workload.py
"""
工况识别API路由 - 支持多LLM切换和OCR集成
"""

import logging
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional
from pydantic import BaseModel
from datetime import datetime

from app.services.workload_recognition_service import (
    get_workload_service, 
    switch_global_llm,
    WorkloadResult,
    TestType, 
    LLMProvider
)
from app.services.usage_tracker import track_usage_simple

logger = logging.getLogger(__name__)
router = APIRouter()

class WorkloadTextRequest(BaseModel):
    """文本输入请求"""
    text: str
    language: str = "zh"
    
class WorkloadOCRRequest(BaseModel):
    """OCR输入请求"""
    ocr_parameters: Dict[str, str]
    language: str = "zh"

class LLMSwitchRequest(BaseModel):
    """LLM切换请求"""
    llm_provider: str  # "qwen" 或 "cerebras"

@router.post("/recognize/text", response_model=WorkloadResult)
# @track_usage_simple("workload_text")
async def recognize_from_text(request: WorkloadTextRequest):
    """从文本识别工况"""
    logger.info(f"[工况识别] 文本输入识别，长度: {len(request.text)}")
    
    try:
        service = get_workload_service()
        result = await service.recognize_from_text(request.text, request.language)
        
        logger.info(f"[工况识别] 识别完成，测试类型: {result.test_type}, 阶段数: {result.total_phases}")
        return result
        
    except Exception as e:
        logger.error(f"[工况识别] 文本识别失败: {e}")
        raise HTTPException(500, f"工况识别失败: {str(e)}")

@router.post("/recognize/ocr", response_model=WorkloadResult)
# @track_usage_simple("workload_ocr")
async def recognize_from_ocr(request: WorkloadOCRRequest):
    """从OCR结果识别工况"""
    logger.info(f"[工况识别] OCR输入识别，参数数量: {len(request.ocr_parameters)}")
    
    try:
        service = get_workload_service()
        result = await service.recognize_from_ocr(request.ocr_parameters, request.language)
        
        logger.info(f"[工况识别] OCR识别完成，测试类型: {result.test_type}, 阶段数: {result.total_phases}")
        return result
        
    except Exception as e:
        logger.error(f"[工况识别] OCR识别失败: {e}")
        raise HTTPException(500, f"OCR工况识别失败: {str(e)}")

@router.post("/switch-llm")
async def switch_llm(request: LLMSwitchRequest):
    """切换LLM提供商 - 修复版本"""
    logger.info(f"[工况识别] 切换LLM请求: {request.llm_provider}")
    
    try:
        # 验证LLM提供商
        if request.llm_provider.lower() == "qwen":
            new_provider = LLMProvider.QWEN
        elif request.llm_provider.lower() == "cerebras":
            new_provider = LLMProvider.CEREBRAS
        else:
            raise ValueError(f"不支持的LLM提供商: {request.llm_provider}")
        
        # 获取服务实例并执行切换
        service = get_workload_service()
        await service.switch_llm(new_provider)
        
        logger.info(f"[工况识别] LLM切换完成: {new_provider.value}")
        
        return {
            "success": True,
            "message": f"LLM已切换到: {new_provider.value}",
            "current_llm": new_provider.value,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"[工况识别] LLM切换失败: {e}")
        raise HTTPException(500, f"LLM切换失败: {str(e)}")

@router.get("/supported-llms")
async def get_supported_llms():
    """获取支持的LLM列表"""
    return {
        "supported_llms": [
            {
                "provider": "qwen",
                "name": "通义千问 Qwen-Plus",
                "description": "阿里云大语言模型，中文优化，功能完整",
                "features": ["中文优化", "COT推理", "参数提取", "工作模式解析"]
            },
            {
                "provider": "cerebras", 
                "name": "Cerebras CS-3",
                "description": "超高速推理芯片，毫秒级响应",
                "features": ["超高速推理", "低延迟", "实时响应"]
            }
        ],
        "default": "qwen",
        "switch_endpoint": "/workload/switch-llm"
    }

@router.get("/json-structure")
async def get_json_structure():
    """获取新JSON结构规范"""
    return {
        "structure_version": "3.0",
        "description": "压缩机测试流程JSON结构生成原则",
        "main_fields": {
            "test_type": "测试类型：耐久测试/性能测试",
            "suction_pressure_tolerance": "吸气标准差",
            "discharge_pressure_tolerance": "排气标准差", 
            "ambient_temp": "环境温度",
            "pressure_standard": "气压类型：绝对气压/表压",
            "total_phases": "分解出来的阶段总数",
            "phases": "阶段定义字典",
            "flow": "执行流程树"
        },
        "phase_structure": {
            "suction_pressure": "吸气压力(MPa)",
            "discharge_pressure": "排气压力(MPa)",
            "voltage": "电压(V)",
            "superheat": "过热度",
            "subcooling": "过冷度",
            "initial_speed": "初始转速(rpm)",
            "target_speed": "目标转速(rpm)",
            "speed_duration": "转速持续时间(s)",
            "initial_temp": "起始温度(°C)",
            "target_temp": "目标温度(°C)",
            "temp_change_rate": "温度变化率(°C/s)",
            "temp_duration": "温度持续时间(s)"
        },
        "flow_node_types": {
            "phase": {"type": "phase", "phase_id": "阶段ID"},
            "sequence": {"type": "sequence", "children": "子节点数组"},
            "loop": {"type": "loop", "count": "循环次数", "children": "子节点数组"}
        },
        "auto_calculation_rules": [
            "若initial_temp ≠ target_temp，则temp_duration = abs(target - initial) / temp_change_rate",
            "若initial_speed ≠ target_speed，则speed_duration = abs(target - initial) / speed_change_rate",
            "所有温度单位统一为摄氏度（°C）",
            "温度变化率单位为°C/s（不是°C/min）",
            "默认压力单位为绝对压力MPa(A)",
            "室温按照20°C计算"
        ]
    }

@router.get("/test-types")
async def get_supported_test_types():
    """获取支持的测试类型"""
    return {
        "supported_types": [
            {
                "code": "ENDURANCE",
                "name": "耐久测试",
                "description": "长时间运行可靠性测试，包含温度循环",
                "required_params": [
                    "吸气压力", "排气压力", "电压", "过热度", 
                    "过冷度", "转速", "环温", "低温停留时间"
                ],
                "tolerances": {"suction": 0.01, "discharge": 0.02}
            },
            {
                "code": "PERFORMANCE", 
                "name": "性能测试",
                "description": "性能指标和效率测试",
                "required_params": [
                    "吸气压力", "排气压力", "电压", "转速", "环温"
                ],
                "tolerances": {"suction": 0.005, "discharge": 0.01}
            }
        ]
    }

@router.get("/status")
async def get_service_status():
    """获取工况识别服务状态"""
    try:
        service = get_workload_service()
        status = service.get_service_status()
        
        return {
            **status,
            "endpoints": [
                "/workload/recognize/text - 文本工况识别（新JSON结构）",
                "/workload/recognize/ocr - OCR工况识别（新JSON结构）",
                "/workload/switch-llm - 切换LLM提供商",
                "/workload/supported-llms - 支持的LLM列表", 
                "/workload/json-structure - JSON结构规范",
                "/workload/test-types - 支持的测试类型",
                "/workload/status - 服务状态",
                "/workload/test - 服务测试"
            ]
        }
        
    except Exception as e:
        logger.error(f"[工况识别] 状态检查失败: {e}")
        return {
            "service": "工况识别服务",
            "status": "错误",
            "error": str(e)
        }

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
        result = await service.recognize_from_text(test_text)
        
        return {
            "test_status": "成功",
            "test_input": "标准耐久测试描述",
            "test_result": {
                "test_type": result.test_type,
                "total_phases": result.total_phases,
                "phase_count": len(result.phases),
                "flow_type": result.flow.type,
                "has_validation_errors": len(result.validation_errors) > 0,
                "processing_info": result.processing_info
            },
            "json_structure": "新版本3.0结构",
            "message": "工况识别服务测试通过（新JSON结构）"
        }
        
    except Exception as e:
        logger.error(f"[工况识别] 测试失败: {e}")
        return {
            "test_status": "失败",
            "error": str(e),
            "message": "工况识别服务测试失败"
        }