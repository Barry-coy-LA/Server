# app/schemas/ocr.py
from pydantic import BaseModel

class OCRResponse(BaseModel):
    text: str  # 将 parameters 改为 text，存储用分号连接的全部文字