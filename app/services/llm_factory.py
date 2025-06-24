# app/services/llm_factory.py
"""
LLM工厂 - 统一管理多种LLM服务
"""

from enum import Enum
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger(__name__)

class LLMProvider(Enum):
    """LLM提供商枚举"""
    QWEN = "qwen"
    CEREBRAS = "cerebras"
    OPENAI = "openai"  # 预留
    CLAUDE = "claude"  # 预留

class LLMFactory:
    """LLM工厂类"""
    
    def __init__(self):
        self.providers = {}
        self._init_providers()
    
    def _init_providers(self):
        """初始化可用的LLM提供商"""
        
        # 初始化Cerebras
        try:
            from .cerebras_service import get_cerebras_service
            cerebras_service = get_cerebras_service()
            if cerebras_service:
                self.providers[LLMProvider.CEREBRAS] = cerebras_service
                logger.info("✅ Cerebras LLM提供商已注册")
        except Exception as e:
            logger.warning(f"⚠️ Cerebras LLM提供商注册失败: {e}")
        
        # 初始化Qwen (如果配置了)
        try:
            from .workload_config import workload_config
            qwen_config = workload_config.get_qwen_config()
            if qwen_config.get('api_key'):
                # Qwen使用HTTP API，不需要单独的服务类
                self.providers[LLMProvider.QWEN] = "configured"
                logger.info("✅ Qwen LLM提供商已注册")
        except Exception as e:
            logger.warning(f"⚠️ Qwen LLM提供商注册失败: {e}")
    
    def get_provider(self, provider_type: LLMProvider):
        """获取LLM提供商实例"""
        return self.providers.get(provider_type)
    
    def is_available(self, provider_type: LLMProvider) -> bool:
        """检查LLM提供商是否可用"""
        return provider_type in self.providers
    
    def get_available_providers(self) -> List[LLMProvider]:
        """获取所有可用的LLM提供商"""
        return list(self.providers.keys())
    
    async def test_all_providers(self) -> Dict[str, Any]:
        """测试所有LLM提供商"""
        results = {}
        
        for provider_type in self.providers:
            try:
                if provider_type == LLMProvider.CEREBRAS:
                    service = self.providers[provider_type]
                    result = await service.test_connection()
                    results[provider_type.value] = result
                elif provider_type == LLMProvider.QWEN:
                    # Qwen测试可以在这里实现
                    results[provider_type.value] = {
                        "status": "configured",
                        "message": "Qwen API已配置"
                    }
                
            except Exception as e:
                results[provider_type.value] = {
                    "status": "error",
                    "error": str(e)
                }
        
        return results

# 全局LLM工厂实例
llm_factory = LLMFactory()
