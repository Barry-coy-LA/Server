# app/routers/face_recognition.py - 带统计追踪的人脸识别路由
from fastapi import APIRouter, File, UploadFile, HTTPException, Form, Request
from fastapi.responses import JSONResponse
import face_recognition
import numpy as np
import cv2
import json
import base64
import logging
from typing import List, Dict, Any
from datetime import datetime
from app.schemas.face_recognition import (
    FaceRecognitionRequest, 
    FaceRecognitionResponse,
    FaceEncodingRequest,
    FaceEncodingResponse
)
from app.services.usage_tracker import track_usage_simple, ServiceType

logger = logging.getLogger(__name__)
router = APIRouter()

def load_image_from_upload(file: UploadFile) -> np.ndarray:
    """从上传的文件加载图像"""
    try:
        # 读取文件内容
        contents = file.file.read()
        
        # 将字节转换为numpy数组
        nparr = np.frombuffer(contents, np.uint8)
        
        # 解码图像
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if image is None:
            raise ValueError("无法解码图像")
            
        # 转换为RGB格式（face_recognition需要RGB格式）
        image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        
        return image_rgb
    except Exception as e:
        logger.error(f"[FACE] 加载图像失败: {str(e)}")
        raise HTTPException(status_code=400, detail=f"图像加载失败: {str(e)}")

def encode_face_encoding(encoding: np.ndarray) -> str:
    """将人脸编码转换为可存储的字符串格式"""
    return base64.b64encode(encoding.tobytes()).decode('utf-8')

def decode_face_encoding(encoding_str: str) -> np.ndarray:
    """将字符串格式的人脸编码转换回numpy数组"""
    try:
        bytes_data = base64.b64decode(encoding_str.encode('utf-8'))
        return np.frombuffer(bytes_data, dtype=np.float64)
    except Exception as e:
        logger.error(f"[FACE] 解码人脸编码失败: {str(e)}")
        raise ValueError(f"无效的人脸编码格式: {str(e)}")

@router.post("/register", response_model=FaceEncodingResponse)
@track_usage_simple(ServiceType.FACE_REGISTER)
async def register_face(
    request: Request,
    file: UploadFile = File(...),
    username: str = Form(...)
):
    """人脸注册 - 工业级生物识别注册"""
    logger.info(f"[FACE] 开始为操作员 {username} 注册生物识别信息")
    
    try:
        # 验证文件类型
        if not file.content_type.startswith('image/'):
            logger.warning(f"[FACE] 无效文件类型: {file.content_type}")
            raise HTTPException(status_code=400, detail="只支持图像文件")
        
        # 加载图像
        image = load_image_from_upload(file)
        
        # 检测人脸位置
        face_locations = face_recognition.face_locations(image)
        
        if len(face_locations) == 0:
            logger.warning(f"[FACE] 未检测到人脸: {username}")
            return FaceEncodingResponse(
                success=False,
                message="未检测到人脸，请确保照片中有清晰的人脸",
                username=username
            )
        
        if len(face_locations) > 1:
            logger.warning(f"[FACE] 检测到多张人脸: {username}")
            return FaceEncodingResponse(
                success=False,
                message="检测到多张人脸，请确保照片中只有一张人脸",
                username=username
            )
        
        # 提取人脸编码
        face_encodings = face_recognition.face_encodings(image, face_locations)
        
        if len(face_encodings) == 0:
            logger.warning(f"[FACE] 无法提取人脸特征: {username}")
            return FaceEncodingResponse(
                success=False,
                message="无法提取人脸特征，请使用更清晰的照片",
                username=username
            )
        
        # 编码人脸特征
        face_encoding = face_encodings[0]
        encoded_face = encode_face_encoding(face_encoding)
        
        logger.info(f"[FACE] 操作员 {username} 生物识别注册成功")
        
        return FaceEncodingResponse(
            success=True,
            message="生物识别注册成功",
            username=username,
            face_encoding=encoded_face
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[FACE] 生物识别注册失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"生物识别注册失败: {str(e)}")

@router.post("/verify", response_model=FaceRecognitionResponse)
@track_usage_simple(ServiceType.FACE_VERIFY)
async def verify_face(
    request: Request,
    file: UploadFile = File(...),
    username: str = Form(...),
    stored_encoding: str = Form(...)
):
    """人脸验证 - 工业级身份认证"""
    logger.info(f"[FACE] 开始验证操作员 {username} 的身份")
    
    try:
        # 验证文件类型
        if not file.content_type.startswith('image/'):
            logger.warning(f"[FACE] 无效文件类型: {file.content_type}")
            raise HTTPException(status_code=400, detail="只支持图像文件")
        
        # 加载当前图像
        current_image = load_image_from_upload(file)
        
        # 检测当前图像中的人脸
        current_face_locations = face_recognition.face_locations(current_image)
        
        if len(current_face_locations) == 0:
            logger.warning(f"[FACE] 验证失败 - 未检测到人脸: {username}")
            return FaceRecognitionResponse(
                success=False,
                message="未检测到人脸，请正对摄像头",
                username=username,
                confidence=0.0
            )
        
        if len(current_face_locations) > 1:
            logger.warning(f"[FACE] 验证失败 - 检测到多张人脸: {username}")
            return FaceRecognitionResponse(
                success=False,
                message="检测到多张人脸，请确保只有授权人员在摄像头前",
                username=username,
                confidence=0.0
            )
        
        # 提取当前人脸编码
        current_face_encodings = face_recognition.face_encodings(current_image, current_face_locations)
        
        if len(current_face_encodings) == 0:
            logger.warning(f"[FACE] 验证失败 - 无法提取人脸特征: {username}")
            return FaceRecognitionResponse(
                success=False,
                message="无法提取人脸特征，请调整光线和角度",
                username=username,
                confidence=0.0
            )
        
        # 解码存储的人脸编码
        try:
            stored_face_encoding = decode_face_encoding(stored_encoding)
        except ValueError as e:
            logger.error(f"[FACE] 无效的存储编码: {username}")
            return FaceRecognitionResponse(
                success=False,
                message="存储的生物识别数据无效，请重新注册",
                username=username,
                confidence=0.0
            )
        
        # 比较人脸
        current_encoding = current_face_encodings[0]
        
        # 计算人脸距离（越小越相似）
        face_distances = face_recognition.face_distance([stored_face_encoding], current_encoding)
        face_distance = face_distances[0]
        
        # 转换为相似度百分比（距离越小，相似度越高）
        confidence = max(0, (1 - face_distance) * 100)
        
        # 工业级认证阈值（更严格）
        RECOGNITION_THRESHOLD = 0.6  # 距离阈值
        MIN_CONFIDENCE = 65.0  # 最小置信度（提高到65%）
        
        is_match = face_distance < RECOGNITION_THRESHOLD and confidence >= MIN_CONFIDENCE
        
        if is_match:
            logger.info(f"[FACE] 操作员 {username} 身份验证成功，置信度: {confidence:.2f}%")
            return FaceRecognitionResponse(
                success=True,
                message=f"身份验证成功，访问权限已授予 - 置信度: {confidence:.1f}%",
                username=username,
                confidence=confidence
            )
        else:
            logger.warning(f"[FACE] 操作员 {username} 身份验证失败，置信度: {confidence:.2f}%")
            return FaceRecognitionResponse(
                success=False,
                message=f"身份验证失败，访问被拒绝 - 置信度过低: {confidence:.1f}%",
                username=username,
                confidence=confidence
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[FACE] 身份验证失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"身份验证失败: {str(e)}")

@router.post("/detect", response_model=FaceEncodingResponse)
@track_usage_simple(ServiceType.FACE_DETECT)
async def detect_face(
    request: Request,
    file: UploadFile = File(...),
    username: str = Form(...)
):
    """人脸检测 - 检测图像中的人脸数量"""
    logger.info(f"[FACE] 开始人脸检测: {username}")
    
    try:
        # 验证文件类型
        if not file.content_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="只支持图像文件")
        
        # 加载图像
        image = load_image_from_upload(file)
        
        # 检测人脸
        face_locations = face_recognition.face_locations(image)
        face_count = len(face_locations)
        
        logger.info(f"[FACE] 检测到 {face_count} 张人脸")
        
        return FaceEncodingResponse(
            success=True,
            message=f"检测完成，发现 {face_count} 张人脸",
            username=username,
            face_encoding=f"detected_{face_count}_faces"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[FACE] 人脸检测失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"人脸检测失败: {str(e)}")

@router.get("/test", tags=["Face Recognition"])
async def test_face_recognition():
    """测试生物识别系统状态"""
    try:
        # 检查face_recognition库是否正常
        test_image = np.zeros((100, 100, 3), dtype=np.uint8)
        face_recognition.face_locations(test_image)
        
        return {
            "status": "OPERATIONAL",
            "service": "Biometric Security System",
            "version": "2.0.0",
            "security_level": "INDUSTRIAL_GRADE",
            "features": [
                "操作员身份验证",
                "危险区域准入控制", 
                "设备操作权限管理",
                "安全事件实时告警"
            ],
            "available_endpoints": [
                "/face/register - 生物识别注册",
                "/face/verify - 身份验证", 
                "/face/detect - 人脸检测",
                "/face/test - 系统测试"
            ]
        }
    except Exception as e:
        logger.error(f"[FACE] 生物识别系统测试失败: {str(e)}")
    raise HTTPException(status_code=500, detail=f"系统异常: {str(e)}")

@router.post("/detect", response_model=FaceEncodingResponse)
async def detect_face_redirect(
    request: Request,
    file: UploadFile = File(...),
    username: str = Form(...)
):
    """
    兼容性端点 - 重定向到 register 端点
    """
    logger.warning("使用了已弃用的 /face/detect 端点，请使用 /face/register")
    return await register_face(request, file, username)

@router.get("/test", tags=["Face Recognition"])
async def test_face_recognition():
    """测试人脸识别服务是否正常工作"""
    try:
        # 检查face_recognition库是否正常
        test_image = np.zeros((100, 100, 3), dtype=np.uint8)
        face_recognition.face_locations(test_image)
        
        return {
            "status": "success",
            "message": "人脸识别服务正常",
            "library_version": face_recognition.__version__ if hasattr(face_recognition, '__version__') else "unknown",
            "available_endpoints": [
                "/face/register - 注册人脸",
                "/face/verify - 验证人脸", 
                "/face/recognize - (已弃用) 重定向到 verify",
                "/face/detect - (已弃用) 重定向到 register",
                "/face/test - 服务测试"
            ]
        }
    except Exception as e:
        logger.error(f"人脸识别服务测试失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"服务异常: {str(e)}")