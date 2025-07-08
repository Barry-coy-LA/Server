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

class Phase(BaseModel):
    """阶段模型 - 按照新规范定义"""
    suction_pressure: float = Field(..., description="吸气压力(MPa)")
    discharge_pressure: float = Field(..., description="排气压力(MPa)")
    voltage: float = Field(..., description="电压(V)")
    superheat: float = Field(..., description="过热度")
    subcooling: float = Field(..., description="过冷度")
    initial_speed: float = Field(..., description="初始转速(rpm)")
    target_speed: float = Field(..., description="目标转速(rpm)")
    speed_duration: float = Field(..., description="转速持续时间(s)")
    initial_temp: float = Field(..., description="起始温度(°C)")
    target_temp: float = Field(..., description="目标温度(°C)")
    temp_change_rate: float = Field(..., description="温度变化率(°C/s)")
    temp_duration: float = Field(..., description="温度持续时间(s)")

from typing import Dict, List, Any, Optional, Union, ForwardRef
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum


class FlowNode(BaseModel):
    """流程节点基类"""
    type: str = Field(..., description="节点类型: phase/sequence/loop")
    
    class Config:
        # 确保子类能正确序列化
        validate_assignment = True
        arbitrary_types_allowed = True

class PhaseNode(FlowNode):
    """阶段引用节点"""
    type: str = Field(default="phase", description="节点类型")
    phase_id: str = Field(..., description="阶段ID")

class SequenceNode(FlowNode):
    """顺序执行节点"""
    type: str = Field(default="sequence", description="节点类型")
    children: List[FlowNode] = Field(default_factory=list, description="子节点列表")

class LoopNode(FlowNode):
    """循环执行节点"""
    type: str = Field(default="loop", description="节点类型")
    count: int = Field(..., description="循环次数")
    children: List[FlowNode] = Field(default_factory=list, description="子节点列表")

try:
    # Pydantic v2
    SequenceNode.model_rebuild()
    LoopNode.model_rebuild()
except AttributeError:
    try:
        # Pydantic v1
        SequenceNode.update_forward_refs()
        LoopNode.update_forward_refs()
    except AttributeError:
        # 如果都不支持，则跳过（某些情况下仍能正常工作）
        pass

class WorkloadResult(BaseModel):
    """工况识别结果 - 新JSON结构"""
    test_type: str = Field(..., description="测试类型")
    suction_pressure_tolerance: float = Field(..., description="吸气标准差")
    discharge_pressure_tolerance: float = Field(..., description="排气标准差")
    ambient_temp: float = Field(default=20.0, description="环境温度")
    pressure_standard: str = Field(default="绝对气压", description="气压类型")
    total_phases: int = Field(..., description="分解出来的阶段总数")
    phases: Dict[str, Phase] = Field(..., description="阶段定义")
    flow: Dict[str, Any] = Field(..., description="执行流程（已序列化）")  # 改为Dict类型
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
            max_tokens = kwargs.get('max_tokens', 3000)
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
                'cerebras': workload_config.get_cerebras_config(),
                'mcp': workload_config.get_mcp_config(),
                'features': workload_config.get('features', {}),
                'validation_rules': workload_config.get_validation_rules()
            }
        except ImportError:
            logger.warning("配置文件未找到，使用默认配置")
            return {
                'qwen': {
                    'api_key': 'csk-jcwvt9ejntw6xm4hj2k5jkrnytnwpedtf23j5v6kv2ytxx54',
                    'api_url': 'https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation',
                    'model': 'qwen-plus',
                    'temperature': 0.1,
                    'max_tokens': 3000,
                    'timeout': 60.0
                },
                'cerebras': {'enabled': False},
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
            config = self.config.get('cerebras', {})
        else:
            raise ValueError(f"不支持的LLM提供商: {provider}")
        
        return CustomLLM(provider, config)
    
    def _build_processing_chain(self) -> SequentialChain:
        """构建LangChain处理链"""
        
        # 1. 测试类型判断链
        async def test_type_classifier(inputs):
            prompt = self._build_test_type_prompt(inputs["text"])
            if self.llm:
                response = await self.llm.ainvoke([HumanMessage(content=prompt)])
                test_type = self._parse_test_type(response)
            else:
                test_type = "耐久测试"  # 默认值
            return {"test_type": test_type}
        
        test_type_chain = TransformChain(
            input_variables=["text"],
            output_variables=["test_type"],
            transform=test_type_classifier
        )
        
        # 2. 参数提取链
        async def parameter_extractor(inputs):
            prompt = self._build_params_extraction_prompt(inputs["text"])
            if self.llm:
                response = await self.llm.ainvoke([HumanMessage(content=prompt)])
                params = self._parse_json_response(response)
            else:
                params = {}
            return {"extracted_params": params}
        
        params_chain = TransformChain(
            input_variables=["text"],
            output_variables=["extracted_params"],
            transform=parameter_extractor
        )
        
        # 3. 阶段分解链
        async def phase_analyzer(inputs):
            prompt = self._build_phases_analysis_prompt(inputs["text"], inputs["test_type"])
            if self.llm:
                response = await self.llm.ainvoke([HumanMessage(content=prompt)])
                phases_data = self._parse_json_response(response)
            else:
                phases_data = {"phases": {}}
            return {"phases_data": phases_data}
        
        phases_chain = TransformChain(
            input_variables=["text", "test_type"],
            output_variables=["phases_data"],
            transform=phase_analyzer
        )
        
        # 4. 流程构建链
        async def flow_builder(inputs):
            phases_json = json.dumps(inputs["phases_data"], ensure_ascii=False)
            prompt = self._build_flow_construction_prompt(inputs["text"], phases_json)
            if self.llm:
                response = await self.llm.ainvoke([HumanMessage(content=prompt)])
                flow_data = self._parse_json_response(response)
            else:
                flow_data = {"flow": {"type": "phase", "phase_id": "1"}}
            return {"flow_data": flow_data}
        
        flow_chain = TransformChain(
            input_variables=["text", "phases_data"],
            output_variables=["flow_data"],
            transform=flow_builder
        )
        
        # 组合成序列链 - 修复变量依赖关系
        processing_chain = SequentialChain(
            chains=[test_type_chain, params_chain, phases_chain, flow_chain],
            input_variables=["text"],
            output_variables=["test_type", "extracted_params", "phases_data", "flow_data"],
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

        测试描述：
        {text}

        请分析测试描述中的关键词和测试目的，只回答"耐久测试"或"性能测试"。
        """
    
    def _build_params_extraction_prompt(self, text: str) -> str:
        """构建参数提取提示词"""
        return f"""
        从以下测试描述中提取关键参数，输出标准JSON格式。

        需要提取的参数包括：
        - 吸气压力 (可能多个)
        - 排气压力 (可能多个)
        - 电压
        - 过热度
        - 过冷度
        - 转速（可能多个）
        - 环温
        - 低温（如果有）
        - 高温（如果有）
        - 温度变化速率（如果有，可能多个）
        - 低温停留时间（如果有）
        - 工作模式 (如果有)

        测试描述：
        {text}

        **重要：必须只返回JSON格式，不要任何其他文字说明！**

        请输出JSON格式，不要包含markdown代码块，例如：
        {{
            "吸气压力": "0.1±0.01MPa",
            "排气压力": "1.0±0.02MPa",
            "转速1": "800±50rmp",
            "转速2": "11000rmp",
            "过热度": "10±1°C",
            "过冷度": "5°C",
            "环温": "-20℃±1°C",
            "电压": "650±5V",
            "工作模式": "具体的工作模式描述"
        }}
        """
    
    def _build_phases_analysis_prompt(self, text: str, test_type: str) -> str:
        """构建工作模式解析提示词"""
        return f"""
        分析以下{test_type}的工作模式，将其分解为独立的测试阶段(phase)。

        每个阶段需要包含完整的参数：
        - suction_pressure: 吸气压力(MPa) - 数值类型
        - discharge_pressure: 排气压力(MPa) - 数值类型  
        - voltage: 电压(V) - 数值类型
        - superheat: 过热度 - 数值类型
        - subcooling: 过冷度 - 数值类型
        - initial_speed: 初始转速(rpm) - 数值类型
        - target_speed: 目标转速(rpm) - 数值类型
        - speed_duration: 转速持续时间(s) - 数值类型
        - initial_temp: 起始温度(°C) - 数值类型
        - target_temp: 目标温度(°C) - 数值类型
        - temp_change_rate: 温度变化率(°C/s) - 数值类型，注意是秒不是分钟
        - temp_duration: 温度持续时间(s) - 数值类型


        注意：
        1. 每个阶段不仅温度可能变化，吸排气压力、转速也可能发生变化
        2. 如果某参数在阶段中保持不变，initial和target值相同
        3. 温度变化率单位为°C/s（注意：1°C/min = 0.0167°C/s）
        4. 所有数值字段必须是纯数字，不要包含单位
        5. 自动推导持续时间：duration = abs(target - initial) / rate
        6. 阶段ID从"1"开始，不要从"0"开始
        7. speed_duration >= duration
        8. 没有特别指出，一般情况下初始转速和目标转速是相同
        9. 上一个阶段的target_speed和下一个阶段的initial_speed是没有关系的

        **示例:**
        输入: "产品在环境温度75°C下开启，运行工况：吸气压力：0.3Mpa，排气压力：2.5Mpa，电压：650+-5V，过热度：10±1°C，过冷度：5°C，转速：11000rmp，以1°C/min逐步调节至最高温度120°C。到达120后，压缩机工作循环（启动10min后关闭2min）持续4800次"
        输出：
        {{
            "phases": {{
                "1": {{
                    "suction_pressure": 0.3,
                    "discharge_pressure": 2.5,
                    "voltage": "650 V",
                    "superheat": "10.00°C",
                    "subcooling": "5.00°C",
                    "initial_speed": 11000.0,
                    "target_speed": 11000.0,
                    "speed_duration": 2700.0,
                    "initial_temp": 75.0,
                    "target_temp": 120.0,
                    "temp_change_rate": 0.0167,
                    "temp_duration": 2700.0
                }},
                "2": {{
                    "suction_pressure": 0.3,
                    "discharge_pressure": 2.5,
                    "voltage": "650.00V",
                    "superheat": "10.00°C",
                    "subcooling": "5.00°C",
                    "initial_speed": 11000.0,
                    "target_speed": 11000.0,
                    "speed_duration": 600.0,
                    "initial_temp": 120.0,
                    "target_temp": 120.0,
                    "temp_change_rate": 0.0,
                    "temp_duration": 600.0
                }},
                "3": {{
                    "suction_pressure": 0.3,
                    "discharge_pressure": 2.5,
                    "voltage": "650.00V",
                    "superheat": "10.00°C",
                    "subcooling": "5.00°C",
                    "initial_speed": 0,
                    "target_speed": 0,
                    "speed_duration": 120.0,
                    "initial_temp": 120.0,
                    "target_temp": 120.0,
                    "temp_change_rate": 0.0,
                    "temp_duration": 120.0
                }}
            }}
        }}

        **示例**:
        输入：最高工作温度85℃，最低工作温度-10℃，最高转速9600rpm时，按照排气压力2.5MPaA测试。最低转速600rpm 模式2：额定电压、排气压力1.0MPaA，吸气压力0.3MpaA，过热度10℃，过冷度5℃，最低转速运行；模式3：额定电压、排气压力2.5MpaA，吸气压力0.3MpaA，过热度10℃，过冷度5℃，做高转速运行；在室温环境温度下开启，按照模式2，运行16min中后到达最低工作温度，按照模式2，保持30min中的最低工作温度，随后36min中升到最高工作温度，前18分钟按照模式2，后18min按照模式3，保持在最高工作温度模式2运行30min，最后按照模式2，15min中下降到室温。整个测试需要450个循环周期
        
        **思维过程:**
        需要计算温度变化率
        1. **阶段1**: 从室温开始，按照模式2运行16分钟，达到-10℃，温度变化率：-10-20/(16*60) = -0.03125°C/s
        2. **阶段2**: 保持-10℃，按照模式2运行30分钟，记录温度和转速
        3. **阶段3**: 升温到37.5℃，按照模式2运行18分钟，温度变化率：37.5-(-10)/(18*60) = 0.04399°C/s
        4. **阶段4**: 升温到85℃，按照模式3运行18分钟，温度变化率：85-37.5/(18*60) = 0.04399°C/s
        5. **阶段5**: 保持在85℃，按照模式2运行30分钟，记录温度和转速
        6. **阶段6**: 降温到室温，按照模式2运行15分钟，温度变化率：20-85/(15*60) = -0.07222°C/s

        输出：
        {{
            "phases": {{
                "1": {{
                    "suction_pressure": 0.3,
                    "discharge_pressure": 1.0,
                    "voltage": 650.0,
                    "superheat": 10.0,
                    "subcooling": 5.0,
                    "initial_speed": 600.0,
                    "target_speed": 600.0,
                    "speed_duration": 960.0,
                    "initial_temp": 20.0,
                    "target_temp": -10.0,
                    "temp_change_rate": -0.03125,
                    "temp_duration": 960.0
                }},
                "2": {{
                    "suction_pressure": 0.3,
                    "discharge_pressure": 1.0,
                    "voltage": 650.0,
                    "superheat": 10.0,
                    "subcooling": 5.0,
                    "initial_speed": 600.0,
                    "target_speed": 600.0,
                    "speed_duration": 1800.0,
                    "initial_temp": -10.0,
                    "target_temp": -10.0,
                    "temp_change_rate": 0.0,
                    "temp_duration": 1800.0
                }},
                "3": {{
                    "suction_pressure": 0.3,
                    "discharge_pressure": 1.0,
                    "voltage": 650.0,
                    "superheat": 10.0,
                    "subcooling": 5.0,
                    "initial_speed": 600.0,
                    "target_speed": 600.0,
                    "speed_duration": 1080.0,
                    "initial_temp": -10.0,
                    "target_temp": 37.5,
                    "temp_change_rate": 0.04399,
                    "temp_duration": 1080.0
                }},
                "4": {{
                    "suction_pressure": 0.3,
                    "discharge_pressure": 2.5,
                    "voltage": 650.0,
                    "superheat": 10.0,
                    "subcooling": 5.0,
                    "initial_speed": 600.0,
                    "target_speed": 9600.0,
                    "speed_duration": 1080.0,
                    "initial_temp": 37.5,
                    "target_temp": 85.0,
                    "temp_change_rate": 0.04399,
                    "temp_duration": 1080.0
                }},
                "5": {{
                    "suction_pressure": 0.3,
                    "discharge_pressure": 1.0,
                    "voltage": 650.0,
                    "superheat": 10.0,
                    "subcooling": 5.0,
                    "initial_speed": 600.0,
                    "target_speed": 600.0,
                    "speed_duration": 1800.0,
                    "initial_temp": 85.0,
                    "target_temp": 85.0,
                    "temp_change_rate": 0.0,
                    "temp_duration": 1800.0
                }},
                "6": {{
                    "suction_pressure": 0.3,
                    "discharge_pressure": 1.0,
                    "voltage": 650.0,
                    "superheat": 10.0,
                    "subcooling": 5.0,
                    "initial_speed": 600.0,
                    "target_speed": 600.0,
                    "speed_duration": 900.0,
                    "initial_temp": 85.0,
                    "target_temp": 20.0,
                    "temp_change_rate": -0.07222,
                    "temp_duration": 900.0
                }}
            }}
        }}

        测试描述：
        {text}

        **重要：必须只返回JSON格式，不要任何其他文字说明！**
        **只返回JSON，格式如下（不要任何其他文字）：**

        请输出JSON格式，包含phases字典，例如：
        {{
            "phases": {{
                "1": {{
                    "suction_pressure": 0.3,
                    "discharge_pressure": 2.5,
                    "voltage": "650 V",
                    "superheat": "10.00°C",
                    "subcooling": "5.00°C",
                    "initial_speed": 11000.0,
                    "target_speed": 11000.0,
                    "speed_duration": 2700.0,
                    "initial_temp": 75.0,
                    "target_temp": 120.0,
                    "temp_change_rate": 1.0,
                    "temp_duration": 2700.0
                }},
            }}
        }}
        """
    def _build_flow_construction_prompt(self, text: str, phases: str) -> str:
        """构建流程构造提示词"""
        return f"""
        根据测试描述和已分解的阶段，构建测试执行流程(flow)。

        流程可以包含三种节点类型：
        1. phase节点：{{"type": "phase", "phase_id": "1"}}
        2. sequence节点：{{"type": "sequence", "children": [...]}}
        3. loop节点：{{"type": "loop", "count": 100, "children": [...]}}
         **示例:**
        输入: 
        测试描述
        "产品在环境温度75°C下开启，运行工况：吸气压力：0.3Mpa，排气压力：2.5Mpa，电压：650+-5V，过热度：10±1°C，过冷度：5°C，转速：11000rmp，以1°C/min逐步调节至最高温度120°C。到达120后，压缩机工作循环（启动10min后关闭2min）持续4800次"
        
        已分解的阶段
        {{
            "phases": {{
                "1": {{
                    "suction_pressure": 0.3,
                    "discharge_pressure": 2.5,
                    "voltage": "650 V",
                    "superheat": "10.00°C",
                    "subcooling": "5.00°C",
                    "initial_speed": 11000.0,
                    "target_speed": 11000.0,
                    "speed_duration": 2700.0,
                    "initial_temp": 75.0,
                    "target_temp": 120.0,
                    "temp_change_rate": 1.0,
                    "temp_duration": 2700.0
                }},
                "2": {{
                    "suction_pressure": 0.3,
                    "discharge_pressure": 2.5,
                    "voltage": "650.00V",
                    "superheat": "10.00°C",
                    "subcooling": "5.00°C",
                    "initial_speed": 11000.0,
                    "target_speed": 11000.0,
                    "speed_duration": 600.0,
                    "initial_temp": 120.0,
                    "target_temp": 120.0,
                    "temp_change_rate": 0.0,
                    "temp_duration": 600.0
                }},
                "3": {{
                    "suction_pressure": 0.3,
                    "discharge_pressure": 2.5,
                    "voltage": "650.00V",
                    "superheat": "10.00°C",
                    "subcooling": "5.00°C",
                    "initial_speed": 0,
                    "target_speed": 0,
                    "speed_duration": 120.0,
                    "initial_temp": 120.0,
                    "target_temp": 120.0,
                    "temp_change_rate": 0.0,
                    "temp_duration": 120.0
                }}
            }}
        }}
        思维过程:
        1. 整个测试阶段是否需要循环执行？如果是，使用loop节点否者判断是否有不止一个节点
        2. 如果有多个阶段，使用sequence节点将它们串联起来
        3. 每个阶段使用phase节点引用已分解的阶段
        4. 检查到达120°C后是否需要循环执行？如果是，children创建，使用loop节点
        5.  **循环**: 重复阶段2和3，共4800次

        输出：
        {{
            "flow": 
            {{ 
                "type": "sequence",
                "children": [
                    {{ 
                        "type": "phase", 
                        "phaseId": "1"
                    }},
                    {{ 
                        "type": "loop", 
                        "count": 4800,
                        "children": [
                            {{ 
                                "type": "phase", 
                                "phaseId": "2"
                            }},
                            {{ 
                                "type": "phase", 
                                "phaseId": "3"
                            }}
                        ]
                    }}
                ]
            }}
        }}

        测试描述：
        {text}

        已分解的阶段：
        {phases}

        **重要：必须只返回JSON格式，不要任何其他文字说明！**
        **只返回JSON，格式如下（不要任何其他文字）：**
        请分析测试流程，构建flow结构。输出纯JSON格式，不要包含markdown代码块，例如：
        {{
            "flow": {{
                "type": "sequence",
                "children": [
                    {{"type": "phase", "phase_id": "1"}},
                    {{
                        "type": "loop",
                        "count": 5,
                        "children": [
                            {{"type": "phase", "phase_id": "2"}},
                            {{"type": "phase", "phase_id": "3"}}
                        ]
                    }}
                ]
            }}
        }}
        """
    
    async def switch_llm(self, new_provider: LLMProvider):
        """切换LLM提供商"""
        logger.info(f"切换LLM: {self.preferred_llm.value} -> {new_provider.value}")
        try:
            # 保存旧的LLM以防回退
            old_llm = self.llm
            old_provider = self.preferred_llm
            
            # 尝试初始化新的LLM
            self.preferred_llm = new_provider
            self.llm = self._init_llm(new_provider)
            
            # 重新构建处理链（虽然结构相同，但需要引用新的LLM）
            self.processing_chain = self._build_processing_chain()
            
            logger.info(f"✅ LLM切换完成: {new_provider.value}")
            
        except Exception as e:
            logger.error(f"❌ LLM切换失败: {e}")
            # 回退到原来的LLM
            self.llm = old_llm
            self.preferred_llm = old_provider
            self.processing_chain = self._build_processing_chain()
            raise RuntimeError(f"LLM切换失败: {str(e)}")
    
    async def recognize_from_text(self, input_text: str, language: str = "zh") -> WorkloadResult:
        """从文本识别工况 - 使用LangChain多阶段处理"""
        logger.info(f"开始工况识别，输入长度: {len(input_text)}, LLM: {self.preferred_llm.value}")
        start_time = datetime.now()
        
        try:
            # 使用LangChain处理链进行多阶段处理
            if self.processing_chain and self.llm:
                logger.info("🔗 使用LangChain处理链")
                
                # 由于LangChain的TransformChain不支持异步，我们手动执行各阶段
                # 第一步：判断测试类型
                test_type_prompt = self._build_test_type_prompt(input_text)
                test_type_response = await self.llm.ainvoke([HumanMessage(content=test_type_prompt)])
                test_type = self._parse_test_type(test_type_response)
                logger.info(f"✅ 测试类型: {test_type}")
                
                # 第二步：提取基础参数
                params_prompt = self._build_params_extraction_prompt(input_text)
                params_response = await self.llm.ainvoke([HumanMessage(content=params_prompt)])
                extracted_params = self._parse_json_response(params_response)
                logger.info(f"✅ 提取参数: {len(extracted_params)} 个")
                
                # 第三步：分解阶段
                phases_prompt = self._build_phases_analysis_prompt(input_text, test_type)
                phases_response = await self.llm.ainvoke([HumanMessage(content=phases_prompt)])
                phases_data = self._parse_json_response(phases_response)
                logger.info(f"✅ 分解阶段: {len(phases_data.get('phases', {}))} 个")
                
                # 第四步：构建流程
                flow_prompt = self._build_flow_construction_prompt(input_text, json.dumps(phases_data, ensure_ascii=False))
                flow_response = await self.llm.ainvoke([HumanMessage(content=flow_prompt)])
                flow_data = self._parse_json_response(flow_response)
                logger.info(f"✅ 构建流程完成")
                
            else:
                logger.warning("⚠️ LangChain处理链或LLM不可用，使用默认处理")
                test_type = "耐久测试"
                extracted_params = {}
                phases_data = {"phases": {"1": self._get_default_phase()}}
                flow_data = {"flow": {"type": "phase", "phase_id": "1"}}
            
            # 第五步：调用MCP进行单位转换和校验
            standardized_params = await self._call_mcp_unit_converter(extracted_params)
            validation_result = await self._call_mcp_physics_validator(standardized_params)

            if "flow" in flow_data:
                actual_flow_data = flow_data["flow"]  # ✅ 提取真正的flow数据
            else:
                actual_flow_data = flow_data
            
            # 第六步：构建最终结果
            processing_time = (datetime.now() - start_time).total_seconds()
            result = self._build_final_result(
                test_type,
                phases_data.get('phases', {}),
                actual_flow_data,  # 使用处理过的flow数据
                validation_result,
                {
                    "llm_used": self.preferred_llm.value,
                    "processing_time": processing_time,
                    "language": language,
                    "langchain_used": bool(self.processing_chain and self.llm)
                }
            )
            
            logger.info(f"✅ 工况识别完成，耗时: {processing_time:.2f}s")
            return result
            
        except Exception as e:
            logger.error(f"❌ 工况识别失败: {e}")
            raise

    def _get_default_phase(self) -> Dict[str, Any]:
        """获取默认阶段数据"""
        return {
            "suction_pressure": 0.1,
            "discharge_pressure": 1.0,
            "voltage": 650,
            "superheat": 10,
            "subcooling": 5,
            "initial_speed": 800,
            "target_speed": 800,
            "speed_duration": 3600,
            "initial_temp": 20,
            "target_temp": 20,
            "temp_change_rate": 0,
            "temp_duration": 3600
        }
    
    async def recognize_from_ocr(self, ocr_params: Dict[str, str], language: str = "zh") -> WorkloadResult:
        """从OCR结果识别工况"""
        logger.info(f"从OCR结果识别工况，参数: {len(ocr_params)} 个")
        
        # 将OCR参数转换为文本描述
        text_description = self._ocr_params_to_text(ocr_params)
        logger.info(f"转换为文本描述: {text_description[:200]}...")
        
        return await self.recognize_from_text(text_description, language)
    
    def _parse_test_type(self, response: str) -> str:
        """解析测试类型"""
        response = response.strip()
        if "耐久测试" in response:
            return "耐久测试"
        elif "性能测试" in response:
            return "性能测试"
        else:
            # 默认判断
            if any(keyword in response.lower() for keyword in ["耐久", "寿命", "长期", "循环"]):
                return "耐久测试"
            else:
                return "性能测试"
    
    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """解析JSON响应 - 支持markdown代码块"""
        try:
            # 直接解析JSON
            return json.loads(response)
        except json.JSONDecodeError:
            try:
                # 尝试提取markdown代码块中的JSON
                import re
                
                # 匹配 ```json ... ``` 格式
                json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response, re.DOTALL | re.IGNORECASE)
                if json_match:
                    json_content = json_match.group(1).strip()
                    logger.info(f"从markdown代码块中提取JSON: {json_content[:100]}...")
                    return json.loads(json_content)
                
                # 匹配普通的 {...} 格式
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    json_content = json_match.group().strip()
                    logger.info(f"从文本中提取JSON: {json_content[:100]}...")
                    return json.loads(json_content)
                    
            except json.JSONDecodeError as e:
                logger.warning(f"JSON解析仍然失败: {e}")
                pass
            
            # 解析失败，返回空字典
            logger.warning(f"JSON解析失败，响应内容: {response[:500]}...")
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
    
    def _build_final_result(self, test_type: str, phases_data: Dict[str, Any], 
                          flow_data: Dict[str, Any], validation_result: Dict[str, Any],
                          processing_info: Dict[str, Any]) -> WorkloadResult:
        """构建最终结果"""
        # 根据测试类型设置容差
        if test_type == TestType.ENDURANCE.value or test_type == "耐久测试":
            tolerances = {"suction": 0.01, "discharge": 0.02}
        else:  # PERFORMANCE
            tolerances = {"suction": 0.005, "discharge": 0.01}
        
        # 构建阶段字典 - 处理数据类型转换
        phases = {}
        for phase_id, phase_data in phases_data.items():
            try:
                # 确保所有数值字段是正确的类型
                cleaned_phase_data = {}
                for key, value in phase_data.items():
                    if key in ['suction_pressure', 'discharge_pressure', 'voltage', 'superheat', 'subcooling',
                              'initial_speed', 'target_speed', 'speed_duration', 'initial_temp', 'target_temp',
                              'temp_change_rate', 'temp_duration']:
                        # 转换为数值类型
                        if isinstance(value, str):
                            # 移除可能的单位和符号
                            import re
                            numeric_value = re.search(r'([-+]?\d*\.?\d+)', str(value))
                            if numeric_value:
                                cleaned_phase_data[key] = float(numeric_value.group(1))
                            else:
                                cleaned_phase_data[key] = 0.0
                        else:
                            cleaned_phase_data[key] = float(value) if value is not None else 0.0
                    else:
                        cleaned_phase_data[key] = value
                
                phases[phase_id] = Phase(**cleaned_phase_data)
                
            except Exception as e:
                logger.warning(f"阶段{phase_id}数据转换失败: {e}, 使用默认值")
                phases[phase_id] = Phase(**self._get_default_phase())
        
        # 如果没有阶段数据，创建一个默认阶段
        if not phases:
            phases["1"] = Phase(**self._get_default_phase())
        
        # 构建流程节点
        logger.info(f"开始构建流程节点，flow_data: {flow_data}")
        try:
            flow_node = self._build_flow_node(flow_data)
            logger.info(f"流程节点构建完成: type={flow_node.type}")
            
            # 测试序列化以确保children被正确包含
            try:
                # 使用自定义序列化方法
                flow_dict = self._serialize_flow_node(flow_node)
                logger.info(f"flow节点序列化测试: {json.dumps(flow_dict, ensure_ascii=False)[:200]}...")
                
                # 验证children是否在序列化结果中
                if 'children' in flow_dict:
                    logger.info(f"✅ children字段已包含在序列化结果中，数量: {len(flow_dict.get('children', []))}")
                else:
                    logger.warning("⚠️ children字段未在序列化结果中")
                    
            except Exception as e:
                logger.error(f"flow节点序列化失败: {e}")
                # 如果序列化失败，创建一个简单的默认节点
                flow_node = PhaseNode(phase_id="1")
            
        except Exception as e:
            logger.error(f"流程节点构建失败: {e}, 使用默认节点")
            flow_node = PhaseNode(phase_id="1")
        
        return WorkloadResult(
            test_type=test_type,  # 直接使用字符串，不需要.value
            suction_pressure_tolerance=tolerances["suction"],
            discharge_pressure_tolerance=tolerances["discharge"],
            total_phases=len(phases),
            phases=phases,
            flow=self._serialize_flow_node(flow_node),  # 使用自定义序列化
            validation_errors=validation_result.get("errors", []),
            processing_info=processing_info
        )    
    
    def _build_flow_node(self, flow_data: Dict[str, Any]) -> FlowNode:
        """递归构建流程节点"""
        if not flow_data or "type" not in flow_data:
            logger.warning("flow_data为空或缺少type字段，返回默认phase节点")
            return PhaseNode(phase_id="1")
        
        node_type = flow_data["type"]
        logger.info(f"构建节点类型: {node_type}")
        
        if node_type == "phase":
            # 兼容 phaseId 和 phase_id 两种字段名
            phase_id = flow_data.get("phase_id") or flow_data.get("phaseId", "1")
            logger.info(f"构建phase节点，phase_id: {phase_id}")
            return PhaseNode(type="phase", phase_id=str(phase_id))
            
        elif node_type == "sequence":
            children = []
            children_data = flow_data.get("children", [])
            logger.info(f"构建sequence节点，子节点数量: {len(children_data)}")
            
            for i, child_data in enumerate(children_data):
                logger.info(f"处理子节点{i}: {child_data}")
                try:
                    child_node = self._build_flow_node(child_data)
                    children.append(child_node)
                    logger.info(f"子节点{i}构建成功: type={child_node.type}")
                except Exception as e:
                    logger.error(f"子节点{i}构建失败: {e}")
            
            logger.info(f"sequence节点构建完成，实际子节点数量: {len(children)}")
            # 直接创建SequenceNode
            return SequenceNode(type="sequence", children=children)
            
        elif node_type == "loop":
            children = []
            children_data = flow_data.get("children", [])
            count = flow_data.get("count", 1)
            logger.info(f"构建loop节点，循环次数: {count}, 子节点数量: {len(children_data)}")
            
            for i, child_data in enumerate(children_data):
                logger.info(f"处理循环子节点{i}: {child_data}")
                try:
                    child_node = self._build_flow_node(child_data)
                    children.append(child_node)
                    logger.info(f"循环子节点{i}构建成功: type={child_node.type}")
                except Exception as e:
                    logger.error(f"循环子节点{i}构建失败: {e}")
            
            logger.info(f"loop节点构建完成，实际子节点数量: {len(children)}")
            # 直接创建LoopNode
            return LoopNode(type="loop", count=count, children=children)
            
        else:
            logger.warning(f"未知的节点类型: {node_type}，使用默认phase节点")
            return PhaseNode(phase_id="1")
        
    def _serialize_flow_node(self, node: FlowNode) -> Dict[str, Any]:
        """自定义序列化Flow节点，确保所有字段都被包含"""
        if isinstance(node, PhaseNode):
            return {
                "type": node.type,
                "phase_id": node.phase_id
            }
        elif isinstance(node, SequenceNode):
            return {
                "type": node.type,
                "children": [self._serialize_flow_node(child) for child in node.children]
            }
        elif isinstance(node, LoopNode):
            return {
                "type": node.type,
                "count": node.count,
                "children": [self._serialize_flow_node(child) for child in node.children]
            }
        else:
            # 回退到默认序列化
            return node.dict()
    
    def _ocr_params_to_text(self, ocr_params: Dict[str, str]) -> str:
        """将OCR参数转换为文本描述"""
        lines = []
        for key, value in ocr_params.items():
            lines.append(f"{key}：{value}")
        return "\n".join(lines)
    
    def get_service_status(self) -> Dict[str, Any]:
        """获取服务状态"""
        return {
            "service": "工况识别服务",
            "version": "3.0.0",
            "current_llm": self.preferred_llm.value if self.llm else "None",
            "mcp_server": self.mcp_url,
            "features": {
                "langchain_integration": True,
                "multi_llm_support": True,
                "mcp_validation": True,
                "ocr_integration": True,
                "new_json_structure": True,
                "phase_flow_separation": True
            },
            "supported_test_types": ["耐久测试", "性能测试"],
            "json_structure": {
                "phases": "独立阶段定义，支持压力、转速、温度全参数变化",
                "flow": "递归流程结构，支持phase/sequence/loop节点",
                "auto_duration": "自动推导温度和转速变化持续时间"
            },
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