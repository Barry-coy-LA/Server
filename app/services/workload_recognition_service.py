# app/services/workload_recognition_service.py
"""
工况识别服务 - 基于LangChain的多LLM支持
技术栈：Qwen3 + Cerebras + LangChain + MCP
"""

import json
import logging
import asyncio
import httpx
from typing import Dict, List, Any, Optional, Union
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum

# LangChain imports
from langchain.chains import TransformChain, SequentialChain
from langchain.schema import BaseMessage, HumanMessage, SystemMessage
from langchain.callbacks.base import BaseCallbackHandler

logger = logging.getLogger(__name__)

class TestType(Enum):
    """测试类型枚举"""
    ENDURANCE = "耐久测试"
    PERFORMANCE = "性能测试"

class LLMProvider(Enum):
    """LLM提供商枚举"""
    QWEN = "qwen"
    CEREBRAS = "cerebras"

class WorkloadStage(BaseModel):
    """工况阶段模型"""
    stage_number: int = Field(..., description="阶段序号")
    suction_pressure: float = Field(..., description="吸气压力(MPa)")
    discharge_pressure: float = Field(..., description="排气压力(MPa)")
    voltage: str = Field(..., description="电压")
    superheat: str = Field(..., description="过热度")
    subcooling: str = Field(..., description="过冷度")
    speed: str = Field(..., description="转速")
    ambient_temp: str = Field(..., description="环境温度")
    initial_temp: float = Field(..., description="初始温度(°C)")
    target_temp: float = Field(..., description="目标温度(°C)")
    temp_change_rate: float = Field(..., description="温度变化率(°C/min)")
    duration: float = Field(..., description="持续时间(秒)")

class WorkloadResult(BaseModel):
    """工况识别结果"""
    test_type: TestType
    suction_pressure_tolerance: float = Field(..., description="吸气压力判稳")
    discharge_pressure_tolerance: float = Field(..., description="排气压力判稳")
    pressure_standard: str = Field(default="绝对压力", description="气压标准")
    total_stages: int = Field(..., description="阶段总数")
    stages: List[WorkloadStage] = Field(..., description="各阶段详情")
    validation_errors: List[str] = Field(default=[], description="校验错误")
    processing_info: Dict[str, Any] = Field(default={}, description="处理信息")

class WorkloadCallbackHandler(BaseCallbackHandler):
    """工况识别回调处理器"""
    
    def __init__(self):
        self.chain_logs = []
        self.processing_time = {}
    
    def on_chain_start(self, serialized, inputs, **kwargs):
        chain_name = serialized.get("name", "unknown")
        self.processing_time[chain_name] = datetime.now()
        logger.info(f"[LangChain] 开始执行链: {chain_name}")
    
    def on_chain_end(self, outputs, **kwargs):
        for chain_name, start_time in self.processing_time.items():
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"[LangChain] 链执行完成: {chain_name}, 耗时: {duration:.2f}s")

class CustomLLM:
    """自定义LLM包装器，支持多种LLM提供商"""
    
    def __init__(self, provider: LLMProvider, config: Dict[str, Any]):
        self.provider = provider
        self.config = config
        self._init_provider()
    
    def _init_provider(self):
        """初始化LLM提供商"""
        if self.provider == LLMProvider.CEREBRAS:
            try:
                from app.services.cerebras_service import get_cerebras_service
                self.service = get_cerebras_service()
                if not self.service:
                    raise RuntimeError("Cerebras服务未配置")
                logger.info("✅ Cerebras LLM已初始化")
            except Exception as e:
                logger.error(f"❌ Cerebras初始化失败: {e}")
                raise
        
        elif self.provider == LLMProvider.QWEN:
            # Qwen通过HTTP API调用
            if not self.config.get('api_key'):
                raise RuntimeError("Qwen API Key未配置")
            self.service = "qwen_http"
            logger.info("✅ Qwen LLM已配置")
    
    async def ainvoke(self, messages: List[BaseMessage], **kwargs) -> str:
        """异步调用LLM"""
        # 将LangChain消息转换为字符串
        if isinstance(messages, list) and len(messages) > 0:
            prompt = messages[-1].content if hasattr(messages[-1], 'content') else str(messages[-1])
        else:
            prompt = str(messages)
        
        if self.provider == LLMProvider.CEREBRAS:
            return await self._call_cerebras(prompt, **kwargs)
        elif self.provider == LLMProvider.QWEN:
            return await self._call_qwen(prompt, **kwargs)
        else:
            raise ValueError(f"不支持的LLM提供商: {self.provider}")
    
    async def _call_cerebras(self, prompt: str, **kwargs) -> str:
        """调用Cerebras API"""
        try:
            max_tokens = kwargs.get('max_tokens', 2000)
            temperature = kwargs.get('temperature', 0.1)
            
            response = await self.service.simple_completion(
                prompt=prompt,
                max_tokens=max_tokens,
                temperature=temperature
            )
            return response
        except Exception as e:
            logger.error(f"Cerebras调用失败: {e}")
            raise
    
    async def _call_qwen(self, prompt: str, **kwargs) -> str:
        """调用Qwen API"""
        try:
            headers = {
                "Authorization": f"Bearer {self.config['api_key']}",
                "Content-Type": "application/json"
            }
            
            data = {
                "model": self.config.get('model', 'qwen-plus'),
                "input": {
                    "messages": [{"role": "user", "content": prompt}]
                },
                "parameters": {
                    "temperature": kwargs.get('temperature', self.config.get('temperature', 0.1)),
                    "max_tokens": kwargs.get('max_tokens', self.config.get('max_tokens', 3000))
                }
            }
            
            timeout = self.config.get('timeout', 60.0)
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    self.config.get('api_url'), 
                    headers=headers, 
                    json=data
                )
                response.raise_for_status()
                result = response.json()
                
                return result["output"]["choices"][0]["message"]["content"]
                
        except Exception as e:
            logger.error(f"Qwen调用失败: {e}")
            raise

class WorkloadRecognitionService:
    """工况识别服务 - 基于LangChain的多阶段处理"""
    
    def __init__(self, preferred_llm: LLMProvider = LLMProvider.QWEN):
        self.preferred_llm = preferred_llm
        self.mcp_url = "http://localhost:8001"  # MCP服务器地址
        
        # 加载配置
        self.config = self._load_config()
        
        # 初始化LLM
        self.llm = self._init_llm(preferred_llm)
        
        # 初始化LangChain处理链
        self.processing_chain = self._build_processing_chain()
        
        # 回调处理器
        self.callback_handler = WorkloadCallbackHandler()
        
        logger.info(f"工况识别服务已初始化，使用LLM: {preferred_llm.value}")
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置"""
        try:
            from app.services.workload_config import workload_config
            return {
                'qwen': workload_config.get_qwen_config(),
                'mcp': workload_config.get_mcp_config(),
                'features': workload_config.get('features', {}),
                'validation_rules': workload_config.get_validation_rules()
            }
        except ImportError:
            logger.warning("配置文件未找到，使用默认配置")
            return {
                'qwen': {'api_key': 'csk-jcwvt9ejntw6xm4hj2k5jkrnytnwpedtf23j5v6kv2ytxx54'},
                'mcp': {'url': 'http://localhost:8001'},
                'features': {'physics_validation': True, 'unit_conversion': True},
                'validation_rules': {}
            }
    
    def _init_llm(self, provider: LLMProvider) -> CustomLLM:
        """初始化LLM"""
        if provider == LLMProvider.QWEN:
            config = self.config['qwen']
            config.update({
                'api_url': 'https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation',
                'model': 'qwen-plus',
                'temperature': 0.1,
                'max_tokens': 3000,
                'timeout': 60.0
            })
        elif provider == LLMProvider.CEREBRAS:
            config = {}
        else:
            raise ValueError(f"不支持的LLM提供商: {provider}")
        
        return CustomLLM(provider, config)
    
    def _build_processing_chain(self) -> SequentialChain:
        """构建LangChain处理链"""
        
        # 1. 测试类型判断链
        def test_type_classifier(inputs):
            return {"test_type_prompt": self._build_test_type_prompt(inputs["text"])}
        
        test_type_chain = TransformChain(
            input_variables=["text"],
            output_variables=["test_type_prompt"],
            transform=test_type_classifier
        )
        
        # 2. 参数提取链
        def parameter_extractor(inputs):
            return {"params_prompt": self._build_params_extraction_prompt(inputs["text"])}
        
        params_chain = TransformChain(
            input_variables=["text"],
            output_variables=["params_prompt"],
            transform=parameter_extractor
        )
        
        # 3. 工作模式解析链
        def work_mode_parser(inputs):
            return {"stages_prompt": self._build_work_mode_prompt(inputs["text"])}
        
        work_mode_chain = TransformChain(
            input_variables=["text"],
            output_variables=["stages_prompt"],
            transform=work_mode_parser
        )
        
        # 组合成序列链
        processing_chain = SequentialChain(
            chains=[test_type_chain, params_chain, work_mode_chain],
            input_variables=["text"],
            output_variables=["test_type_prompt", "params_prompt", "stages_prompt"],
            verbose=True
        )
        
        return processing_chain
    
    def _build_test_type_prompt(self, text: str) -> str:
        """构建测试类型判断提示词"""
        return f"""
        你是一个制冷系统压缩机测试专家，需要根据测试描述判断测试类型。请按照以下思维步骤进行分析：

        **思维步骤:**
        1. 识别关键词和参数
        2. 分析测试目的和条件
        3. 确定测试类型
        4. 给出判断理由

        **示例:**
        输入: "压缩机低温耐久测试，吸气压力：0.1±0.01MPa，排气压力：1.0±0.02MPa，环温：-20℃±1°C，低温：-40°C±1°C，温度变化速率：1°C/min，低温停留时间：7200min，工作模式：产品在-20℃环境下开启，以1℃/min的变换速率调节至-40℃，保持120h后再以1℃/min的变化速率恢复至常温。"

        思维过程:
        1. **关键词识别**: "低温耐久测试"、"温度变化速率"、"低温停留时间"、"保持120h"
        2. **测试目的分析**: 验证设备在低温环境下长时间运行的可靠性
        3. **测试条件分析**: 有温度循环(-20℃→-40℃→常温)、长时间保温(120h)、特定变化速率(1℃/min)
        4. **测试类型判断**: 耐久测试 - 因为包含长期运行(120h)、温度循环、可靠性验证等特征

        输出: 耐久测试

        {text}

        请分析测试描述中的关键词和测试目的，只回答"耐久测试"或"性能测试"。
        """
    
    def _build_params_extraction_prompt(self, text: str) -> str:
        """构建参数提取提示词"""
        return f"""
        从以下测试描述中提取关键参数，输出标准JSON格式。

        需要提取的参数包括：
        - 吸气压力
        - 排气压力  
        - 电压
        - 过热度
        - 过冷度
        - 转速
        - 环温
        - 低温（如果有）
        - 高温（如果有）
        - 温度变化速率（如果有）
        - 低温停留时间（如果有）
        - 工作模式

        测试描述：
        {text}

        请输出JSON格式，例如：
        {{
            "吸气压力": "0.1±0.01MPa",
            "排气压力": "1.0±0.02MPa",
            "电压": "650±5V",
            "工作模式": "具体的工作模式描述"
        }}
        """
    
    def _build_work_mode_prompt(self, text: str) -> str:
        """构建工作模式解析提示词"""
        return f"""
        分析以下测试描述中的工作模式，将其分解为具体的测试阶段。

        每个阶段需要包含：
        - 初始温度
        - 目标温度  
        - 温度变化率（正数表示升温，负数表示降温，0表示保温）
        - 持续时间(s)

        **示例1:**
        输入: "产品在-20℃环境下开启，以1℃/min的变换速率调节至-40℃，保持120h后再以1℃/min的变化速率恢复至常温。"
        输出:
        {{
            "stages": [
                {{
                    "stage_number": 1,
                    "initial_temp": -20,
                    "target_temp": -40,
                    "temp_change_rate": -1,
                    "duration": 1200,
                    "description": "从-20℃降温至-40℃"
                }},
                {{
                    "stage_number": 2,
                    "initial_temp": -40,
                    "target_temp": -40,
                    "temp_change_rate": 0,
                    "duration": 432000,
                    "description": "在-40℃保温120小时（7200分钟）"
                }},
                {{
                    "stage_number": 3,
                    "initial_temp": -40,
                    "target_temp": 25,
                    "temp_change_rate": 1,
                    "duration": 3900,
                    "description": "从-40℃升温至常温（假设常温为25℃）"
                }}
            ]
        }}
        **示例2:**
        产品在环境温度75°C下开启，运行工况：吸气压力：0.1+-0.01Mpa（A），排气压力：1.0+-0.02Mpa（A），电压：650+-5V，过热度：10±1°C，过冷度：5°C，转速：11000rmp，以1°C/min逐步调节至最高温度120°C
        输出:
        {{
            "stages": [
                {{
                    "stage_number": 1,
                    "initial_temp": 75,
                    "target_temp": 120,
                    "temp_change_rate": 1,
                    "duration": 2700,
                    "description": "从75℃升温至120℃"
                }}
            ]
        }}
        测试描述：
        {text}

        请输出JSON格式的阶段列表，例如：
        {{
            "stages": [
                {{
                    "stage_number": 1,
                    "initial_temp": -20,
                    "target_temp": -40,
                    "temp_change_rate": -1,
                    "duration": 1200,
                    "description": "降温阶段"
                }},
                {{
                    "stage_number": 2, 
                    "initial_temp": -40,
                    "target_temp": -40,
                    "temp_change_rate": 0,
                    "duration": 432000,
                    "description": "保温阶段"
                }}
            ]
        }}
        """
    
    async def switch_llm(self, new_provider: LLMProvider):
        """切换LLM提供商"""
        logger.info(f"切换LLM: {self.preferred_llm.value} -> {new_provider.value}")
        self.preferred_llm = new_provider
        self.llm = self._init_llm(new_provider)
        logger.info(f"✅ LLM切换完成: {new_provider.value}")
    
    async def recognize_from_text(self, input_text: str, language: str = "zh") -> WorkloadResult:
        """从文本识别工况 - 使用LangChain多阶段处理"""
        logger.info(f"开始工况识别，输入长度: {len(input_text)}, LLM: {self.preferred_llm.value}")
        start_time = datetime.now()
        
        try:
            # 第一步：判断测试类型
            test_type_prompt = self._build_test_type_prompt(input_text)
            test_type_response = await self.llm.ainvoke([HumanMessage(content=test_type_prompt)])
            test_type = self._parse_test_type(test_type_response)
            logger.info(f"✅ 测试类型: {test_type.value}")
            
            # 第二步：提取参数
            params_prompt = self._build_params_extraction_prompt(input_text)
            params_response = await self.llm.ainvoke([HumanMessage(content=params_prompt)])
            extracted_params = self._parse_json_response(params_response)
            logger.info(f"✅ 提取参数: {len(extracted_params)} 个")
            
            # 第三步：解析工作模式生成阶段
            stages_prompt = self._build_work_mode_prompt(input_text)
            stages_response = await self.llm.ainvoke([HumanMessage(content=stages_prompt)])
            print(stages_response)
            stages_data = self._parse_json_response(stages_response)
            logger.info(f"✅ 解析阶段: {len(stages_data.get('stages', []))} 个")
            
            # 第四步：调用MCP进行单位转换和校验
            standardized_params = await self._call_mcp_unit_converter(extracted_params)
            validation_result = await self._call_mcp_physics_validator(standardized_params)
            
            # 第五步：构建最终阶段
            stages = self._build_workload_stages(stages_data.get('stages', []), standardized_params)
            
            # 第六步：构建最终结果
            processing_time = (datetime.now() - start_time).total_seconds()
            result = self._build_final_result(
                test_type, 
                standardized_params, 
                stages, 
                validation_result, 
                {
                    "llm_used": self.preferred_llm.value,
                    "processing_time": processing_time,
                    "language": language
                }
            )
            
            logger.info(f"✅ 工况识别完成，耗时: {processing_time:.2f}s")
            return result
            
        except Exception as e:
            logger.error(f"❌ 工况识别失败: {e}")
            raise
    
    async def recognize_from_ocr(self, ocr_params: Dict[str, str], language: str = "zh") -> WorkloadResult:
        """从OCR结果识别工况"""
        logger.info(f"从OCR结果识别工况，参数: {len(ocr_params)} 个")
        
        # 将OCR参数转换为文本描述
        text_description = self._ocr_params_to_text(ocr_params)
        logger.info(f"转换为文本描述: {text_description[:200]}...")
        
        return await self.recognize_from_text(text_description, language)
    
    def _parse_test_type(self, response: str) -> TestType:
        """解析测试类型"""
        response = response.strip()
        if "耐久测试" in response:
            return TestType.ENDURANCE
        elif "性能测试" in response:
            return TestType.PERFORMANCE
        else:
            # 默认判断
            if any(keyword in response.lower() for keyword in ["耐久", "寿命", "长期", "循环"]):
                return TestType.ENDURANCE
            else:
                return TestType.PERFORMANCE
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析JSON响应"""
        try:
            # 直接解析JSON
            return json.loads(response)
        except json.JSONDecodeError:
            # 尝试提取JSON部分
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass
            
            # 解析失败，返回空字典
            logger.warning(f"JSON解析失败: {response[:200]}...")
            return {}
    
    async def _call_mcp_unit_converter(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """调用MCP单位转换服务"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.mcp_url}/tools/unit-converter",
                    json={"parameters": params}
                )
                if response.status_code == 200:
                    result = response.json()
                    if result.get("success"):
                        return result.get("result", params)
                
                logger.warning(f"MCP单位转换失败: {response.status_code}")
                return params
                
        except Exception as e:
            logger.error(f"MCP单位转换调用失败: {e}")
            return params
    
    async def _call_mcp_physics_validator(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """调用MCP物理校验服务"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.mcp_url}/tools/physics-validator",
                    json={"parameters": params}
                )
                if response.status_code == 200:
                    result = response.json()
                    if result.get("success"):
                        return result.get("result", {})
                
                logger.warning(f"MCP物理校验失败: {response.status_code}")
                return {"valid": True, "errors": [], "warnings": []}
                
        except Exception as e:
            logger.error(f"MCP物理校验调用失败: {e}")
            return {"valid": True, "errors": [], "warnings": []}
    
    def _build_workload_stages(self, stages_data: List[Dict[str, Any]], 
                             base_params: Dict[str, Any]) -> List[WorkloadStage]:
        """构建工况阶段"""
        stages = []
        
        # 从基础参数中提取固定值
        fixed_params = {
            "suction_pressure": self._parse_pressure(base_params.get("吸气压力", "0.1MPa")),
            "discharge_pressure": self._parse_pressure(base_params.get("排气压力", "1.0MPa")),
            "voltage": base_params.get("电压", "650±5V"),
            "superheat": base_params.get("过热度", "10±1°C"),
            "subcooling": base_params.get("过冷度", "5°C"),
            "speed": base_params.get("转速", "800±50rpm"),
            "ambient_temp": base_params.get("环温", "-20°C±1°C")
        }
        
        for stage_data in stages_data:
            stage = WorkloadStage(
                stage_number=stage_data.get("stage_number", len(stages) + 1),
                initial_temp=float(stage_data.get("initial_temp", 20)),
                target_temp=float(stage_data.get("target_temp", 20)),
                temp_change_rate=float(stage_data.get("temp_change_rate", 0)),
                duration=float(stage_data.get("duration", 3600)),
                **fixed_params
            )
            stages.append(stage)
        
        return stages
    
    def _build_final_result(self, test_type: TestType, params: Dict[str, Any], 
                          stages: List[WorkloadStage], validation_result: Dict[str, Any],
                          processing_info: Dict[str, Any]) -> WorkloadResult:
        """构建最终结果"""
        # 根据测试类型设置容差
        if test_type == TestType.ENDURANCE:
            tolerances = {"suction": 0.01, "discharge": 0.02}
        else:  # PERFORMANCE
            tolerances = {"suction": 0.005, "discharge": 0.01}
        
        return WorkloadResult(
            test_type=test_type,
            suction_pressure_tolerance=tolerances["suction"],
            discharge_pressure_tolerance=tolerances["discharge"],
            total_stages=len(stages),
            stages=stages,
            validation_errors=validation_result.get("errors", []),
            processing_info=processing_info
        )
    
    def _ocr_params_to_text(self, ocr_params: Dict[str, str]) -> str:
        """将OCR参数转换为文本描述"""
        lines = []
        for key, value in ocr_params.items():
            lines.append(f"{key}：{value}")
        return "\n".join(lines)
    
    def _parse_pressure(self, pressure_str: str) -> float:
        """解析压力值"""
        import re
        match = re.search(r'([\d.]+)', str(pressure_str))
        return float(match.group(1)) if match else 0.0
    
    def get_service_status(self) -> Dict[str, Any]:
        """获取服务状态"""
        return {
            "service": "工况识别服务",
            "version": "2.1.0",
            "current_llm": self.preferred_llm.value,
            "mcp_server": self.mcp_url,
            "features": {
                "langchain_integration": True,
                "multi_llm_support": True,
                "mcp_validation": True,
                "ocr_integration": True
            },
            "supported_test_types": [t.value for t in TestType],
            "status": "operational"
        }

# 全局服务实例
_workload_service = None

def get_workload_service(preferred_llm: LLMProvider = LLMProvider.QWEN) -> WorkloadRecognitionService:
    """获取工况识别服务实例"""
    global _workload_service
    if _workload_service is None:
        _workload_service = WorkloadRecognitionService(preferred_llm)
    return _workload_service

def switch_global_llm(new_provider: LLMProvider):
    """切换全局LLM提供商"""
    global _workload_service
    if _workload_service:
        asyncio.create_task(_workload_service.switch_llm(new_provider))
    else:
        _workload_service = WorkloadRecognitionService(new_provider)