# app/services/cerebras_service.py
"""
Cerebras API服务 - 高速推理服务
支持从配置文件和环境变量读取API Key
"""

import os
import logging
import asyncio
from typing import Dict, List, Any, Optional, Union
from datetime import datetime
from pydantic import BaseModel, Field
import httpx

logger = logging.getLogger(__name__)

class CerebrasConfig(BaseModel):
    """Cerebras配置模型"""
    api_key: str = Field(..., description="Cerebras API密钥")
    base_url: str = Field(default="https://api.cerebras.ai/v1", description="API基础URL")
    model: str = Field(default="llama-3.3-70b", description="默认模型")
    timeout: float = Field(default=30.0, description="请求超时时间")
    max_tokens: int = Field(default=2048, description="最大tokens")
    temperature: float = Field(default=0.1, description="温度参数")

class CerebrasMessage(BaseModel):
    """Cerebras消息模型"""
    role: str = Field(..., description="角色: user/assistant/system")
    content: str = Field(..., description="消息内容")

class CerebrasResponse(BaseModel):
    """Cerebras响应模型"""
    id: str
    model: str
    content: str
    finish_reason: str
    usage: Dict[str, Any]  # <- 改为 Any 以支持嵌套对象
    time_info: Dict[str, float]
    created: int

class CerebrasService:
    """Cerebras服务类"""
    
    def __init__(self, config: Optional[CerebrasConfig] = None):
        if config:
            self.config = config
        else:
            # 优先从配置文件加载，然后从环境变量
            api_key = self._get_api_key()
            if not api_key:
                raise ValueError("Cerebras API Key未配置：请在配置文件或环境变量中设置")
            
            # 从配置文件加载其他设置
            cerebras_config = self._load_from_config()
            self.config = CerebrasConfig(
                api_key=api_key,
                base_url=cerebras_config.get('api_url', 'https://api.cerebras.ai/v1'),
                model=cerebras_config.get('model', 'llama-3.3-70b'),
                timeout=cerebras_config.get('timeout', 30.0),
                max_tokens=cerebras_config.get('max_tokens', 2048),
                temperature=cerebras_config.get('temperature', 0.1)
            )
        
        self.client = None
        self._init_client()
        logger.info("Cerebras服务已初始化")
    
    def _get_api_key(self) -> Optional[str]:
        """获取API Key - 优先配置文件，然后环境变量"""
        # 方法1：从配置文件读取
        try:
            config_api_key = self._load_from_config().get('api_key')
            if config_api_key:
                logger.info("✅ 从配置文件加载Cerebras API Key")
                return config_api_key
        except Exception as e:
            logger.warning(f"从配置文件加载API Key失败: {e}")
        
        # 方法2：从环境变量读取
        env_api_key = os.environ.get("CEREBRAS_API_KEY")
        if env_api_key:
            logger.info("✅ 从环境变量加载Cerebras API Key")
            return env_api_key
        
        logger.warning("⚠️ 未找到Cerebras API Key")
        return None
    
    def _load_from_config(self) -> Dict[str, Any]:
        """从配置文件加载Cerebras配置"""
        try:
            from .workload_config import workload_config
            cerebras_config = workload_config.get_cerebras_config()
            logger.info(f"从配置文件加载Cerebras设置: {len(cerebras_config)} 项")
            return cerebras_config
        except ImportError:
            logger.warning("工况配置模块未找到，使用默认配置")
            return {}
        except Exception as e:
            logger.warning(f"加载配置文件失败: {e}")
            return {}
    
    def _init_client(self):
        """初始化Cerebras客户端"""
        try:
            # 尝试导入Cerebras SDK
            from cerebras.cloud.sdk import Cerebras

            self.client = Cerebras(api_key=self.config.api_key,)
            logger.info("✅ Cerebras SDK客户端已初始化")
        except ImportError:
            logger.warning("⚠️ Cerebras SDK未安装，将使用HTTP API")
            self.client = None
    
    async def chat_completion(
        self, 
        messages: List[CerebrasMessage],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> CerebrasResponse:
        """聊天完成API调用"""
        
        # 使用配置默认值
        model = model or self.config.model
        temperature = temperature or self.config.temperature
        max_tokens = max_tokens or self.config.max_tokens
        
        # 转换消息格式
        message_dicts = [{"role": msg.role, "content": msg.content} for msg in messages]
        
        if self.client:
            # 使用官方SDK
            return await self._call_with_sdk(message_dicts, model, temperature, max_tokens)
        else:
            # 使用HTTP API
            return await self._call_with_http(message_dicts, model, temperature, max_tokens)
    
    async def _call_with_sdk(
        self, 
        messages: List[Dict[str, str]], 
        model: str, 
        temperature: float, 
        max_tokens: int
    ) -> CerebrasResponse:
        """使用官方SDK调用"""
        try:
            # 在异步环境中调用同步SDK
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
            )
            
            # 转换响应格式
            choice = response.choices[0]
            return CerebrasResponse(
                id=response.id,
                model=response.model,
                content=choice.message.content,
                finish_reason=choice.finish_reason,
                usage={
                        "prompt_tokens": getattr(response.usage, "prompt_tokens", None),
                        "completion_tokens": getattr(response.usage, "completion_tokens", None),
                        "total_tokens": getattr(response.usage, "total_tokens", None),
                        # 可选：记录详细信息但不映射为 int
                        "prompt_tokens_details": getattr(response.usage, "prompt_tokens_details", None)
                    },

                time_info=response.time_info.__dict__ if hasattr(response, 'time_info') else {},
                created=response.created
            )
            
        except Exception as e:
            logger.error(f"Cerebras SDK调用失败: {e}")
            raise
    
    async def _call_with_http(
        self, 
        messages: List[Dict[str, str]], 
        model: str, 
        temperature: float, 
        max_tokens: int
    ) -> CerebrasResponse:
        """使用HTTP API调用"""
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.post(
                    f"{self.config.base_url}/chat/completions",
                    headers=headers,
                    json=data
                )
                response.raise_for_status()
                result = response.json()
                
                # 解析响应
                choice = result["choices"][0]
                return CerebrasResponse(
                    id=result["id"],
                    model=result["model"],
                    content=choice["message"]["content"],
                    finish_reason=choice["finish_reason"],
                    usage=result.get("usage", {}),
                    time_info=result.get("time_info", {}),
                    created=result["created"]
                )
                
        except Exception as e:
            logger.error(f"Cerebras HTTP API调用失败: {e}")
            raise
    
    async def simple_completion(self, prompt: str, **kwargs) -> str:
        """简单的文本完成"""
        messages = [CerebrasMessage(role="user", content=prompt)]
        response = await self.chat_completion(messages, **kwargs)
        return response.content
    
    async def test_connection(self) -> Dict[str, Any]:
        """测试连接状态"""
        try:
            start_time = datetime.now()
            
            test_messages = [
                CerebrasMessage(role="user", content="Hello, please respond with 'OK'")
            ]
            
            response = await self.chat_completion(
                test_messages, 
                max_tokens=10,
                temperature=0.1
            )
            
            end_time = datetime.now()
            response_time = (end_time - start_time).total_seconds()
            
            return {
                "status": "success",
                "response_time": response_time,
                "model": response.model,
                "content": response.content,
                "usage": response.usage,
                "config_source": "配置文件" if self._load_from_config().get('api_key') else "环境变量"
            }
            
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "response_time": 0,
                "config_source": "未知"
            }
    
    def get_status(self) -> Dict[str, Any]:
        """获取服务状态"""
        config_info = self._load_from_config()
        api_key_source = "配置文件" if config_info.get('api_key') else "环境变量"
        
        return {
            "service": "Cerebras AI Service",
            "configured": bool(self.config.api_key),
            "sdk_available": self.client is not None,
            "model": self.config.model,
            "api_url": self.config.base_url,
            "api_key_source": api_key_source,
            "api_key_length": len(self.config.api_key) if self.config.api_key else 0,
            "timeout": self.config.timeout,
            "max_tokens": self.config.max_tokens
        }

# 全局Cerebras服务实例
_cerebras_service = None

def get_cerebras_service() -> Optional[CerebrasService]:
    """获取Cerebras服务实例"""
    global _cerebras_service
    
    if _cerebras_service is None:
        try:
            _cerebras_service = CerebrasService()
        except ValueError as e:
            logger.warning(f"Cerebras服务初始化失败: {e}")
            return None
    
    return _cerebras_service