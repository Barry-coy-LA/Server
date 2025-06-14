# app/schemas/ocr.py
from pydantic import BaseModel
from typing import Dict

class OCRResponse(BaseModel):
    parameters: Dict[str, str]
