# app/schemas/face_recognition.py
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class FaceRecognitionRequest(BaseModel):
    """人脸识别请求"""
    username: str
    stored_encoding: str
    
class FaceRecognitionResponse(BaseModel):
    """人脸识别响应"""
    success: bool
    message: str
    username: str
    confidence: float
    timestamp: Optional[datetime] = None
    
    def __init__(self, **data):
        if 'timestamp' not in data:
            data['timestamp'] = datetime.now()
        super().__init__(**data)

class FaceEncodingRequest(BaseModel):
    """人脸编码提取请求"""
    username: str
    
class FaceEncodingResponse(BaseModel):
    """人脸编码提取响应"""
    success: bool
    message: str
    username: str
    face_encoding: Optional[str] = None
    timestamp: Optional[datetime] = None
    
    def __init__(self, **data):
        if 'timestamp' not in data:
            data['timestamp'] = datetime.now()
        super().__init__(**data)