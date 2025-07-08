# ===========================================
# app/routers/ocr.py
# ===========================================
import os
import tempfile
from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse
from app.services.ocr_service import extract_parameters
from app.schemas.ocr import OCRResponse
# from app.services.usage_tracker import track_usage_simple  # 如果有使用追踪功能
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/table", response_model=OCRResponse)
# @track_usage_simple("ocr")  # 如果需要使用追踪，取消注释
async def table_ocr(request: Request, file: UploadFile = File(...)):
    """OCR文字识别 - 提取图片中所有文字内容"""
    logger.info(f"[OCR] 接收OCR请求: {file.filename}, 大小: {file.size if hasattr(file, 'size') else 'unknown'}")
    
    # 只支持常见图片格式
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".bmp"):
        logger.warning(f"[OCR] 不支持的文件格式: {ext}")
        raise HTTPException(400, "不支持的文件格式，请使用PNG、JPG、JPEG或BMP格式")

    # 存为临时文件
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        logger.info(f"[OCR] 开始处理文件: {tmp_path}")
        text_result = extract_parameters(tmp_path)  # 现在返回的是连接的文字字符串
        logger.info(f"[OCR] 识别完成，提取文字长度: {len(text_result)} 字符")
        
        return JSONResponse(content={"text": text_result})  # 返回 text 字段而不是 parameters
        
    except Exception as e:
        logger.error(f"[OCR] 处理失败: {str(e)}")
        raise HTTPException(500, f"OCR处理失败: {str(e)}")
    finally:
        # 清理临时文件
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
            logger.debug(f"[OCR] 清理临时文件: {tmp_path}")

@router.get("/test", tags=["OCR"])
async def test_ocr_service():
    """测试OCR服务状态"""
    return {
        "status": "OPERATIONAL",
        "service": "OCR Text Recognition Engine",
        "version": "2.0.0",
        "supported_formats": ["PNG", "JPG", "JPEG", "BMP"],
        "features": [
            "全文字识别",
            "多格式图片支持", 
            "中英文混合识别",
            "文字内容提取"
        ],
        "output_format": "分号分隔的连续文字"
    }