# app/routers/ocr.py
import os
import tempfile
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from app.services.ocr_service import extract_parameters
from app.schemas.ocr import OCRResponse

router = APIRouter()

@router.post("/table", response_model=OCRResponse)
async def table_ocr(file: UploadFile = File(...)):
    # 只支持常见图片格式
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".bmp"):
        raise HTTPException(400, "Unsupported file type")

    # 存为临时文件
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        params = extract_parameters(tmp_path)
    finally:
        os.remove(tmp_path)

    return JSONResponse(content={"parameters": params})
