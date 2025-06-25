# app/mcp_server/main.py
"""
MCP (Model Context Protocol) 独立服务器
提供计算器和JSON构建工具服务
"""

import json
import logging
import re
import math
import os
import sys
from typing import Dict, List, Any, Optional, Union
from datetime import datetime
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# 设置UTF-8编码（解决Windows中文显示问题）
if sys.platform.startswith('win'):
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.detach())
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.detach())

# 配置日志
logging.basicConfig(level=logging.INFO, encoding='utf-8')
logger = logging.getLogger(__name__)

# 从环境变量获取端口，默认8001
MCP_PORT = int(os.environ.get('MCP_PORT', 8001))

app = FastAPI(
    title="MCP工具服务器",
    description="为工况识别提供计算器和JSON构建工具",
    version="1.0.0"
)

# 添加CORS中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求/响应模型
class ToolRequest(BaseModel):
    """工具请求基类"""
    parameters: Dict[str, Any]

class ToolResponse(BaseModel):
    """工具响应基类"""
    success: bool
    result: Dict[str, Any] = {}
    errors: List[str] = []
    processing_time: float = 0.0

class JsonBuilderRequest(BaseModel):
    """JSON构建请求"""
    test_type: str
    stages: List[Dict[str, Any]]
    tolerances: Dict[str, float] = {}

# 单位转换服务
class UnitConverter:
    """单位转换器"""
    
    # 单位转换表
    UNITS = {
        "pressure": {
            "MPa": 1.0,
            "kPa": 0.001,
            "Pa": 0.000001,
            "psi": 0.00689476,
            "bar": 0.1,
            "atm": 0.101325
        },
        "temperature": {
            "°C": {"offset": 0, "scale": 1},
            "℃": {"offset": 0, "scale": 1},
            "K": {"offset": -273.15, "scale": 1},
            "°F": {"offset": -32, "scale": 5/9}
        },
        "time": {
            "s": 1.0,
            "min": 60.0,
            "h": 3600.0,
            "hour": 3600.0,
            "day": 86400.0
        },
        "speed": {
            "rpm": 1.0,
            "rmp": 1.0,  # 常见拼写错误
            "r/min": 1.0,
            "Hz": 60.0
        },
        "voltage": {
            "V": 1.0,
            "kV": 1000.0,
            "mV": 0.001
        }
    }
    
    def detect_unit_and_value(self, text: str) -> tuple:
        """检测文本中的数值、单位和类型"""
        if not isinstance(text, str):
            return 0.0, "", "unknown"
        
        # 移除空格和特殊字符
        text = text.strip().replace('（', '(').replace('）', ')')
        
        # 提取数值（包含±符号）
        value_pattern = r'([\d.]+)(?:\s*[±+\-]\s*[\d.]+)?'
        value_match = re.search(value_pattern, text)
        
        if not value_match:
            return 0.0, "", "unknown"
        
        value = float(value_match.group(1))
        
        # 检测单位类型
        for unit_type, units in self.UNITS.items():
            for unit in units.keys():
                if unit in text:
                    return value, unit, unit_type
        
        return value, "", "unknown"
    
    def convert_to_standard(self, value: float, from_unit: str, unit_type: str) -> float:
        """转换到标准单位"""
        if unit_type not in self.UNITS:
            return value
        
        if from_unit not in self.UNITS[unit_type]:
            return value
        
        if unit_type == "temperature":
            conversion = self.UNITS[unit_type][from_unit]
            return (value + conversion["offset"]) * conversion["scale"]
        else:
            return value * self.UNITS[unit_type][from_unit]
    
    def standardize_parameters(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """标准化所有参数"""
        standardized = {}
        
        for key, value in params.items():
            if isinstance(value, str):
                val, unit, unit_type = self.detect_unit_and_value(value)
                if unit_type != "unknown":
                    standard_val = self.convert_to_standard(val, unit, unit_type)
                    
                    # 添加标准单位后缀
                    standard_units = {
                        "pressure": "MPa", 
                        "temperature": "°C",
                        "time": "s",
                        "speed": "rpm",
                        "voltage": "V"
                    }
                    
                    if unit_type in standard_units:
                        standardized[key] = f"{standard_val:.6f}{standard_units[unit_type]}"
                    else:
                        standardized[key] = standard_val
                else:
                    standardized[key] = value
            else:
                standardized[key] = value
        
        return standardized

# 物理校验服务
class PhysicsValidator:
    """物理逻辑校验器"""
    
    def __init__(self):
        self.errors = []
        self.warnings = []
    
    def validate_pressure_relationship(self, suction_pressure: str, discharge_pressure: str) -> bool:
        """验证压力关系：排气压力应大于吸气压力"""
        try:
            converter = UnitConverter()
            
            suction_val, _, _ = converter.detect_unit_and_value(suction_pressure)
            discharge_val, _, _ = converter.detect_unit_and_value(discharge_pressure)
            
            if discharge_val <= suction_val:
                self.errors.append(f"压力关系错误：排气压力({discharge_val})应大于吸气压力({suction_val})")
                return False
            
            # 检查压比是否合理（通常2-20之间）
            pressure_ratio = discharge_val / suction_val if suction_val > 0 else 0
            if pressure_ratio > 50:
                self.warnings.append(f"压比过高：{pressure_ratio:.2f}，请检查数值是否正确")
            elif pressure_ratio < 1.5:
                self.warnings.append(f"压比过低：{pressure_ratio:.2f}，请检查数值是否正确")
            
            return True
            
        except Exception as e:
            self.errors.append(f"压力关系验证失败：{str(e)}")
            return False
    
    def validate_temperature_change(self, initial_temp: float, target_temp: float, 
                                  rate: float, duration: float) -> bool:
        """验证温度变化逻辑"""
        try:
            # 计算理论时间
            temp_diff = abs(target_temp - initial_temp)
            theoretical_time = temp_diff / abs(rate) if rate != 0 else 0
            
            # 转换为秒
            theoretical_time_seconds = theoretical_time * 60  # rate是°C/min
            
            # 检查时间一致性（允许5%误差）
            time_error = abs(duration - theoretical_time_seconds) / theoretical_time_seconds if theoretical_time_seconds > 0 else 0
            
            if time_error > 0.05:  # 5%误差
                self.errors.append(
                    f"温度变化时间不一致：理论时间{theoretical_time_seconds:.0f}s，"
                    f"实际时间{duration:.0f}s，误差{time_error*100:.1f}%"
                )
                return False
            
            # 检查变化率合理性
            if abs(rate) > 10:
                self.warnings.append(f"温度变化率较高：{rate}°C/min，请确认是否合理")
            
            # 检查温度范围合理性
            if initial_temp < -100 or initial_temp > 200:
                self.warnings.append(f"初始温度超出常见范围：{initial_temp}°C")
            
            if target_temp < -100 or target_temp > 200:
                self.warnings.append(f"目标温度超出常见范围：{target_temp}°C")
            
            return True
            
        except Exception as e:
            self.errors.append(f"温度变化验证失败：{str(e)}")
            return False
    
    def validate_speed_range(self, speed_str: str) -> bool:
        """验证转速范围"""
        try:
            converter = UnitConverter()
            speed_val, unit, _ = converter.detect_unit_and_value(speed_str)
            
            # 转换为rpm
            if unit in ["Hz"]:
                speed_val *= 60
            
            # 检查转速范围（通常100-10000 rpm）
            if speed_val < 10:
                self.warnings.append(f"转速过低：{speed_val} rpm")
            elif speed_val > 20000:
                self.warnings.append(f"转速过高：{speed_val} rpm")
            
            return True
            
        except Exception as e:
            self.errors.append(f"转速验证失败：{str(e)}")
            return False
    
    def validate_all(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """执行所有物理校验"""
        self.errors = []
        self.warnings = []
        
        # 压力关系校验
        if "吸气压力" in params and "排气压力" in params:
            self.validate_pressure_relationship(
                str(params["吸气压力"]), 
                str(params["排气压力"])
            )
        
        # 转速校验
        if "转速" in params:
            self.validate_speed_range(str(params["转速"]))
        
        # 温度变化校验（如果有工作模式）
        work_mode = params.get("工作模式", "")
        if work_mode:
            self._validate_work_mode_consistency(work_mode, params)
        
        return {
            "valid": len(self.errors) == 0,
            "errors": self.errors,
            "warnings": self.warnings
        }
    
    def _validate_work_mode_consistency(self, work_mode: str, params: Dict[str, Any]):
        """验证工作模式一致性"""
        try:
            # 提取工作模式中的温度和时间信息
            temp_pattern = r'(-?\d+)℃'
            time_pattern = r'(\d+)h'
            rate_pattern = r'(\d+)℃/min'
            
            temps = [float(m) for m in re.findall(temp_pattern, work_mode)]
            times = [float(m) for m in re.findall(time_pattern, work_mode)]
            rates = [float(m) for m in re.findall(rate_pattern, work_mode)]
            
            if len(temps) >= 2 and len(rates) >= 1:
                # 验证第一阶段：-20℃到-40℃
                self.validate_temperature_change(temps[0], temps[1], -rates[0], 
                                               abs(temps[1] - temps[0]) / rates[0] * 60)
                
                # 验证保温阶段
                if len(times) >= 1:
                    hold_time_seconds = times[0] * 3600
                    if "低温停留时间" in params:
                        converter = UnitConverter()
                        hold_val, _, _ = converter.detect_unit_and_value(str(params["低温停留时间"]))
                        hold_val_seconds = hold_val * 60  # 分钟转秒
                        
                        if abs(hold_time_seconds - hold_val_seconds) / hold_val_seconds > 0.01:
                            self.errors.append(f"保温时间不一致：工作模式{hold_time_seconds}s vs 参数{hold_val_seconds}s")
        
        except Exception as e:
            self.warnings.append(f"工作模式一致性检查失败：{str(e)}")

# JSON构建服务
class JsonBuilder:
    """JSON结构构建器"""
    
    def __init__(self):
        self.templates = {
            "耐久测试": self._endurance_template,
            "性能测试": self._performance_template
        }
    
    def build_workload_json(self, test_type: str, stages: List[Dict[str, Any]], 
                           tolerances: Dict[str, float] = None) -> Dict[str, Any]:
        """构建工况JSON"""
        if tolerances is None:
            tolerances = {"suction": 0.01, "discharge": 0.02}
        
        # 获取模板函数
        template_func = self.templates.get(test_type, self._default_template)
        
        # 构建基础结构
        result = {
            "工况一": {
                "试验类型": test_type,
                "吸气压力判稳": f"{tolerances.get('suction', 0.01)}MPa",
                "排气压力判稳": f"{tolerances.get('discharge', 0.02)}MPa", 
                "气压标准": "绝对压力",
                "阶段总数": len(stages)
            }
        }
        
        # 添加各阶段
        for i, stage_data in enumerate(stages, 1):
            stage_key = f"阶段{i}"
            result["工况一"][stage_key] = template_func(stage_data, i)
        
        return result
    
    def _endurance_template(self, stage_data: Dict[str, Any], stage_num: int) -> Dict[str, Any]:
        """耐久测试模板"""
        return {
            "吸气压力": f"{stage_data.get('suction_pressure', 0.1):.1f}MPa",
            "排气压力": f"{stage_data.get('discharge_pressure', 1.0):.1f}MPa",
            "电压": stage_data.get('voltage', '650±5V'),
            "过热度": stage_data.get('superheat', '10±1°C'),
            "过冷度": stage_data.get('subcooling', '5°C'),
            "转速": stage_data.get('speed', '800±50rpm'),
            "环温": stage_data.get('ambient_temp', '-20℃±1°C'),
            "初始温度": f"{stage_data.get('initial_temp', 20):.0f}℃",
            "目标温度": f"{stage_data.get('target_temp', 20):.0f}℃",
            "温度变化率": f"{stage_data.get('temp_change_rate', 0):.0f}℃/min",
            "持续时间": f"{stage_data.get('duration', 3600):.0f}s"
        }
    
    def _performance_template(self, stage_data: Dict[str, Any], stage_num: int) -> Dict[str, Any]:
        """性能测试模板"""
        return {
            "吸气压力": f"{stage_data.get('suction_pressure', 0.1):.1f}MPa",
            "排气压力": f"{stage_data.get('discharge_pressure', 1.0):.1f}MPa", 
            "电压": stage_data.get('voltage', '650±5V'),
            "转速": stage_data.get('speed', '800±50rpm'),
            "环温": stage_data.get('ambient_temp', '20℃±1°C'),
            "测试工况": f"工况{stage_num}",
            "持续时间": f"{stage_data.get('duration', 1800):.0f}s"
        }
    
    def _default_template(self, stage_data: Dict[str, Any], stage_num: int) -> Dict[str, Any]:
        """默认模板"""
        return {
            "阶段编号": stage_num,
            "持续时间": f"{stage_data.get('duration', 3600):.0f}s",
            "参数": stage_data
        }

# 初始化服务实例
unit_converter = UnitConverter()
json_builder = JsonBuilder()

# API端点
@app.post("/tools/unit-converter", response_model=ToolResponse)
async def unit_conversion_tool(request: ToolRequest):
    """单位转换工具"""
    start_time = datetime.now()
    
    try:
        logger.info(f"[MCP] 单位转换请求，参数数量: {len(request.parameters)}")
        
        standardized = unit_converter.standardize_parameters(request.parameters)
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        logger.info(f"[MCP] 单位转换完成，耗时: {processing_time:.3f}s")
        
        return ToolResponse(
            success=True,
            result=standardized,
            processing_time=processing_time
        )
        
    except Exception as e:
        logger.error(f"[MCP] 单位转换失败: {e}")
        return ToolResponse(
            success=False,
            errors=[str(e)],
            processing_time=(datetime.now() - start_time).total_seconds()
        )

@app.post("/tools/physics-validator", response_model=ToolResponse)
async def physics_validation_tool(request: ToolRequest):
    """物理校验工具"""
    start_time = datetime.now()
    
    try:
        logger.info(f"[MCP] 物理校验请求，参数数量: {len(request.parameters)}")
        
        # 创建新的验证器实例以避免状态污染
        validator = PhysicsValidator()
        validation_result = validator.validate_all(request.parameters)
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        logger.info(f"[MCP] 物理校验完成，有效: {validation_result['valid']}, 耗时: {processing_time:.3f}s")
        
        return ToolResponse(
            success=True,
            result=validation_result,
            processing_time=processing_time
        )
        
    except Exception as e:
        logger.error(f"[MCP] 物理校验失败: {e}")
        return ToolResponse(
            success=False,
            errors=[str(e)],
            processing_time=(datetime.now() - start_time).total_seconds()
        )

@app.post("/tools/json-builder", response_model=ToolResponse)
async def json_builder_tool(request: JsonBuilderRequest):
    """JSON构建工具"""
    start_time = datetime.now()
    
    try:
        logger.info(f"[MCP] JSON构建请求，测试类型: {request.test_type}, 阶段数: {len(request.stages)}")
        
        result_json = json_builder.build_workload_json(
            request.test_type, 
            request.stages, 
            request.tolerances
        )
        
        processing_time = (datetime.now() - start_time).total_seconds()
        
        logger.info(f"[MCP] JSON构建完成，耗时: {processing_time:.3f}s")
        
        return ToolResponse(
            success=True,
            result=result_json,
            processing_time=processing_time
        )
        
    except Exception as e:
        logger.error(f"[MCP] JSON构建失败: {e}")
        return ToolResponse(
            success=False,
            errors=[str(e)],
            processing_time=(datetime.now() - start_time).total_seconds()
        )

@app.get("/tools/list")
async def list_tools():
    """列出所有可用工具"""
    return {
        "tools": [
            {
                "name": "unit-converter",
                "description": "单位转换工具",
                "endpoint": "/tools/unit-converter",
                "capabilities": [
                    "压力单位转换 (MPa, kPa, psi, bar)",
                    "温度单位转换 (°C, K, °F)",
                    "时间单位转换 (s, min, h)",
                    "转速单位转换 (rpm, Hz)",
                    "电压单位转换 (V, kV, mV)"
                ]
            },
            {
                "name": "physics-validator", 
                "description": "物理逻辑校验工具",
                "endpoint": "/tools/physics-validator",
                "capabilities": [
                    "压力关系校验",
                    "温度变化逻辑校验",
                    "转速范围校验",
                    "工作模式一致性校验"
                ]
            },
            {
                "name": "json-builder",
                "description": "JSON结构构建工具", 
                "endpoint": "/tools/json-builder",
                "capabilities": [
                    "耐久测试JSON构建",
                    "性能测试JSON构建"
                ]
            }
        ],
        "server_info": {
            "name": "MCP工具服务器",
            "version": "1.0.0",
            "status": "运行中",
            "port": MCP_PORT
        }
    }

@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "tools_available": 3,
        "server": "MCP Tools Server",
        "port": MCP_PORT
    }

@app.get("/")
async def root():
    """根路径"""
    return {
        "message": "MCP工具服务器",
        "version": "1.0.0",
        "port": MCP_PORT,
        "docs": "/docs",
        "tools": "/tools/list",
        "health": "/health"
    }

if __name__ == "__main__":
    print("=" * 50)
    print("MCP工具服务器启动")
    print("=" * 50)
    print()
    print(f"服务地址: http://127.0.0.1:{MCP_PORT}")
    print(f"API文档: http://127.0.0.1:{MCP_PORT}/docs")
    print(f"健康检查: http://127.0.0.1:{MCP_PORT}/health")
    print(f"工具列表: http://127.0.0.1:{MCP_PORT}/tools/list")
    print()
    print("可用工具:")
    print("  单位转换器: /tools/unit-converter")
    print("  物理校验器: /tools/physics-validator") 
    print("  JSON构建器: /tools/json-builder")
    print()
    print("提示: 按 Ctrl+C 停止服务器")
    print("=" * 50)
    print()
    
    uvicorn.run(
        app, 
        host="127.0.0.1", 
        port=MCP_PORT,
        log_level="info"
    )