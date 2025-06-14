# app/services/ocr_service.py
import re
import logging
from typing import Dict
from paddleocr import PaddleOCR, PPStructure

# 全局加载模型，后续可在此模块中接入 MCP/RAG 等新功能
_ocr_engine = PaddleOCR(use_angle_cls=True, lang='ch', show_log=False)
_structure  = PPStructure(ocr=_ocr_engine)

def extract_parameters(image_path: str) -> Dict[str, str]:
    """
    使用 PP-Structure 提取表格参数，返回 {参数名: 值}。
    """
    results = _structure(image_path)
    if not results:
        logging.warning(f"No OCR result for {image_path}")
        return {}

    raw_res = results[0]['res']
    params: Dict[str, str] = {}
    for item in raw_res:
        text = item.get('text', '').strip()
        if not text:
            continue
        # 统一冒号，OCR 中“土”→"+-"
        text = text.replace('：', ':')
        text = re.sub(r'\s*土\s*', '+-', text)
        text = re.sub(r'\s*\(.*\)$', '', text)
        if ':' in text:
            k,v = text.split(':', 1)
            params[k.strip()] = v.strip()
    return params
