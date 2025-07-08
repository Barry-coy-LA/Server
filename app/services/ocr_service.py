# app/services/ocr_service.py - 优化版，只返回纯文字内容
import re
import logging
import json
import tempfile
import os
from paddleocr import PaddleOCR

# 全局加载PP-OCRv5模型
_ocr_engine = PaddleOCR(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False
)

def extract_parameters(image_path: str) -> str:
    """
    使用 PP-OCRv5 提取图片中的所有文字，返回用分号连接的文本。
    """
    try:
        # 尝试predict方法
        try:
            result = _ocr_engine.predict(input=image_path)
            text_parts = _extract_from_predict_result(result)
            if text_parts:
                final_result = '；'.join(text_parts)
                logging.info(f"[OCR] Predict方法成功，提取到 {len(text_parts)} 个文本片段")
                return final_result
        except:
            pass
        
        # 备用：传统OCR方法
        results = _ocr_engine.ocr(image_path, cls=True)
        if not results or not results[0]:
            logging.warning(f"[OCR] 未识别到文字内容")
            return ""
        
        text_parts = []
        for line in results[0]:
            if line and len(line) >= 2:
                text_info = line[1]
                raw_text = text_info[0] if isinstance(text_info, (list, tuple)) else text_info
                cleaned_text = _clean_text(raw_text)
                if cleaned_text:
                    text_parts.append(cleaned_text)
        
        final_result = '；'.join(text_parts)
        logging.info(f"[OCR] 传统方法成功，提取到 {len(text_parts)} 个文本片段")
        return final_result
        
    except Exception as e:
        logging.error(f"[OCR] 处理失败: {e}")
        return ""

def _extract_from_predict_result(result) -> list:
    """从predict结果中提取文本"""
    text_parts = []
    
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            for i, res in enumerate(result):
                # 方法1: JSON提取
                try:
                    json_file = os.path.join(temp_dir, f"result_{i}.json")
                    res.save_to_json(json_file)
                    
                    if os.path.exists(json_file):
                        with open(json_file, 'r', encoding='utf-8') as f:
                            ocr_data = json.load(f)
                        text_parts.extend(_extract_texts_from_json(ocr_data))
                except:
                    pass
                
                # 方法2: 属性提取
                try:
                    if hasattr(res, '__dict__'):
                        for attr_name, attr_value in res.__dict__.items():
                            if 'text' in attr_name.lower() and isinstance(attr_value, (str, list)):
                                if isinstance(attr_value, str) and attr_value.strip():
                                    text_parts.append(attr_value.strip())
                                elif isinstance(attr_value, list):
                                    text_parts.extend([str(item).strip() for item in attr_value if str(item).strip()])
                except:
                    pass
    except:
        pass
    
    # 清理和去重
    cleaned_texts = []
    seen = set()
    for text in text_parts:
        cleaned = _clean_text(text)
        if cleaned and cleaned not in seen and _is_meaningful_text(cleaned):
            cleaned_texts.append(cleaned)
            seen.add(cleaned)
    
    return cleaned_texts

def _extract_texts_from_json(ocr_data) -> list:
    """从JSON数据中提取文本"""
    texts = []
    
    def find_text_recursively(data):
        if isinstance(data, dict):
            for key, value in data.items():
                if 'text' in key.lower() or 'content' in key.lower() or 'rec' in key.lower():
                    if isinstance(value, str) and value.strip():
                        texts.append(value.strip())
                    elif isinstance(value, list):
                        texts.extend([str(item).strip() for item in value if str(item).strip()])
                elif isinstance(value, (dict, list)):
                    find_text_recursively(value)
        elif isinstance(data, list):
            for item in data:
                find_text_recursively(item)
    
    try:
        find_text_recursively(ocr_data)
    except:
        pass
    
    return texts

def _is_meaningful_text(text: str) -> bool:
    """
    判断是否是有意义的文本，过滤掉置信度分数、坐标等无关数据
    """
    try:
        # 过滤纯数字（通常是置信度分数）
        if re.match(r'^0\.\d+$', text):
            return False
        
        # 过滤坐标格式 [x, y, x, y] 或 [[x, y], [x, y], ...]
        if re.match(r'^\[.*\]$', text) and (',' in text or ' ' in text):
            return False
        
        # 过滤纯数字
        if text.replace('.', '').replace('-', '').isdigit():
            return False
        
        # 过滤太短的文本（少于2个字符）
        if len(text.strip()) < 2:
            return False
        
        # 过滤只包含特殊符号的文本
        if re.match(r'^[^\w\u4e00-\u9fff]+$', text):
            return False
        
        return True
    except:
        return False

def _clean_text(raw_text) -> str:
    """清理文本"""
    try:
        if not raw_text:
            return ""
        
        text = str(raw_text).strip()
        if not text:
            return ""
        
        # 文本处理
        text = text.replace('：', ':')
        text = re.sub(r'\s*土\s*', '+-', text)
        text = re.sub(r'\s*\([^)]*\)\s*', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        
        # 移除明显的OCR噪音
        # 移除孤立的符号
        text = re.sub(r'^\W+$', '', text)
        
        # 清理特殊字符组合
        text = re.sub(r'\{\\c', '°', text)  # 处理温度符号
        text = re.sub(r'\{\\°', '°', text)
        text = re.sub(r'\$', '', text)  # 移除特殊符号
        
        return text if len(text) > 0 else ""
    except:
        return ""