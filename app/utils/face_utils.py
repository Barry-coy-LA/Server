import face_recognition
import numpy as np
import cv2
import base64
from io import BytesIO
from PIL import Image
import json
import logging

logger = logging.getLogger(__name__)

class FaceRecognitionService:
    """人脸识别服务"""
    
    @staticmethod
    def base64_to_image(base64_str: str) -> np.ndarray:
        """将Base64字符串转换为OpenCV图像"""
        try:
            # 移除base64前缀（如果有）
            if ',' in base64_str:
                base64_str = base64_str.split(',')[1]
            
            # 解码base64
            img_data = base64.b64decode(base64_str)
            
            # 转换为PIL图像
            pil_img = Image.open(BytesIO(img_data))
            
            # 转换为RGB（face_recognition需要RGB格式）
            if pil_img.mode != 'RGB':
                pil_img = pil_img.convert('RGB')
            
            # 转换为numpy数组
            img_array = np.array(pil_img)
            
            return img_array
        except Exception as e:
            logger.error(f"Base64转图像失败: {e}")
            raise
    
    @staticmethod
    def encode_face(image: np.ndarray) -> str:
        """从图像中提取人脸编码"""
        try:
            # 检测人脸位置
            face_locations = face_recognition.face_locations(image)
            
            if not face_locations:
                raise ValueError("未检测到人脸")
            
            if len(face_locations) > 1:
                raise ValueError("检测到多个人脸，请确保图片中只有一个人")
            
            # 提取人脸编码
            face_encodings = face_recognition.face_encodings(image, face_locations)
            
            if not face_encodings:
                raise ValueError("无法提取人脸特征")
            
            # 将numpy数组转换为列表，然后转为JSON字符串
            encoding_list = face_encodings[0].tolist()
            encoding_str = json.dumps(encoding_list)
            
            return encoding_str
        except Exception as e:
            logger.error(f"人脸编码失败: {e}")
            raise
    
    @staticmethod
    def verify_face(image: np.ndarray, stored_encoding_str: str, threshold: float = 0.6) -> tuple[bool, float]:
        """验证人脸是否匹配"""
        try:
            # 从图像中提取人脸编码
            face_locations = face_recognition.face_locations(image)
            
            if not face_locations:
                return False, 0.0
            
            face_encodings = face_recognition.face_encodings(image, face_locations)
            
            if not face_encodings:
                return False, 0.0
            
            # 解析存储的编码
            stored_encoding_list = json.loads(stored_encoding_str)
            stored_encoding = np.array(stored_encoding_list)
            
            # 计算人脸距离
            face_distances = face_recognition.face_distance([stored_encoding], face_encodings[0])
            
            # 距离越小越相似，转换为相似度分数
            distance = face_distances[0]
            confidence = 1.0 - distance
            
            # 判断是否匹配
            is_match = distance <= threshold
            
            return is_match, confidence
        except Exception as e:
            logger.error(f"人脸验证失败: {e}")
            raise