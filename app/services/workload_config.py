"""
工况识别系统配置文件 - 集成Cerebras API配置
"""

import os
from pathlib import Path
from typing import Dict, Any, Optional
import json

class WorkloadConfig:
    """工况识别配置管理"""
    
    def __init__(self):
        self.config_file = Path("Data/workload_config.json")
        self._config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        default_config = {
            "qwen_api": {
                "api_key": "csk-jcwvt9ejntw6xm4hj2k5jkrnytnwpedtf23j5v6kv2ytxx54",
                "api_url": "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                "model": "qwen-plus",
                "temperature": 0.1,
                "max_tokens": 3000,
                "timeout": 60.0
            },
            "cerebras_api": {
                "api_key": "csk-jcwvt9ejntw6xm4hj2k5jkrnytnwpedtf23j5v6kv2ytxx54",
                "api_url": "https://api.cerebras.ai/v1",
                "model": "qwen-3-32b",
                "temperature": 0.1,
                "max_tokens": 2000,
                "timeout": 30.0
            },
            "mcp_server": {
                "url": "http://localhost:8001",
                "timeout": 30.0,
                "retry_attempts": 3,
                "auto_start": False
            },
            "features": {
                "cot_prompts": True,
                "physics_validation": True,
                "unit_conversion": True,
                "multi_language": True,
                "ocr_integration": True,
                "cerebras_support": True
            },
            "test_types": {
                "耐久测试": {
                    "required_params": [
                        "吸气压力", "排气压力", "电压", "过热度", 
                        "过冷度", "转速", "环温", "低温停留时间"
                    ],
                    "tolerances": {
                        "suction": 0.01,
                        "discharge": 0.02
                    }
                },
                "性能测试": {
                    "required_params": [
                        "吸气压力", "排气压力", "电压", "转速", "环温"
                    ],
                    "tolerances": {
                        "suction": 0.005,
                        "discharge": 0.01
                    }
                }
            },
            "validation_rules": {
                "pressure_ratio_max": 50,
                "pressure_ratio_min": 1.5,
                "temp_change_rate_max": 10,
                "temp_range_min": -100,
                "temp_range_max": 200,
                "speed_range_min": 10,
                "speed_range_max": 20000,
                "time_consistency_tolerance": 0.05
            },
            "languages": {
                "zh": "中文",
                "en": "English",
                "ja": "日本語"
            },
            "llm_preferences": {
                "default_provider": "cerebras",
                "fallback_provider": "qwen",
                "performance_mode": True,
                "auto_switch": True
            }
        }
        
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                # 合并默认配置和加载的配置
                self._merge_config(default_config, loaded_config)
                return default_config
            except Exception as e:
                print(f"配置文件加载失败: {e}，使用默认配置")
                return default_config
        else:
            # 创建默认配置文件
            self._save_config(default_config)
            return default_config
    
    def _merge_config(self, default: Dict[str, Any], loaded: Dict[str, Any]):
        """递归合并配置"""
        for key, value in loaded.items():
            if key in default:
                if isinstance(value, dict) and isinstance(default[key], dict):
                    self._merge_config(default[key], value)
                else:
                    default[key] = value
            else:
                default[key] = value
    
    def _save_config(self, config: Dict[str, Any]):
        """保存配置文件"""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"配置文件保存失败: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    
    def set(self, key: str, value: Any):
        """设置配置项"""
        keys = key.split('.')
        config = self._config
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        config[keys[-1]] = value
        self._save_config(self._config)
    
    def get_qwen_config(self) -> Dict[str, Any]:
        """获取Qwen API配置"""
        return self.get('qwen_api', {})
    
    def get_cerebras_config(self) -> Dict[str, Any]:
        """获取Cerebras API配置"""
        return self.get('cerebras_api', {})
    
    def get_mcp_config(self) -> Dict[str, Any]:
        """获取MCP服务器配置"""
        return self.get('mcp_server', {})
    
    def get_test_type_config(self, test_type: str) -> Dict[str, Any]:
        """获取测试类型配置"""
        return self.get(f'test_types.{test_type}', {})
    
    def get_validation_rules(self) -> Dict[str, Any]:
        """获取校验规则"""
        return self.get('validation_rules', {})
    
    def get_llm_preferences(self) -> Dict[str, Any]:
        """获取LLM偏好设置"""
        return self.get('llm_preferences', {})
    
    def is_feature_enabled(self, feature: str) -> bool:
        """检查功能是否启用"""
        return self.get(f'features.{feature}', False)
    
    def get_supported_languages(self) -> Dict[str, str]:
        """获取支持的语言"""
        return self.get('languages', {})
    
    def update_api_key(self, provider: str, api_key: str):
        """更新API密钥"""
        if provider == "qwen":
            self.set('qwen_api.api_key', api_key)
        elif provider == "cerebras":
            self.set('cerebras_api.api_key', api_key)
        print(f"已更新{provider} API密钥")
    
    def get_all_api_keys(self) -> Dict[str, str]:
        """获取所有API密钥状态（不显示实际密钥）"""
        qwen_key = self.get_qwen_config().get('api_key', '')
        cerebras_key = self.get_cerebras_config().get('api_key', '')
        
        return {
            "qwen": "已配置" if qwen_key else "未配置",
            "cerebras": "已配置" if cerebras_key else "未配置",
            "qwen_length": len(qwen_key) if qwen_key else 0,
            "cerebras_length": len(cerebras_key) if cerebras_key else 0
        }

# 全局配置实例
workload_config = WorkloadConfig()