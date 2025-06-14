# app/routers/ocr.py - 带统计追踪的OCR路由
import os
import tempfile
from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from fastapi.responses import JSONResponse
from app.services.ocr_service import extract_parameters
from app.schemas.ocr import OCRResponse
from app.services.usage_tracker import track_usage_simple
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/table", response_model=OCRResponse)
@track_usage_simple("ocr")  # 直接使用字符串
async def table_ocr(request: Request, file: UploadFile = File(...)):
    """OCR表格识别 - 工业级数据提取"""
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
        params = extract_parameters(tmp_path)
        logger.info(f"[OCR] 识别完成，提取到 {len(params)} 个参数")
        
        return JSONResponse(content={"parameters": params})
        
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
        "service": "OCR Analysis Engine",
        "version": "2.0.0",
        "supported_formats": ["PNG", "JPG", "JPEG", "BMP"],
        "features": [
            "工业仪表数据提取",
            "生产报表智能识别", 
            "质检数据自动录入",
            "多格式文档解析"
        ]
    }