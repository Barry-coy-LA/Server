# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.core.config import settings
from app.utils.logger import setup_logging
from app.routers.ocr import router as ocr_router
from app.routers.face_recognition import router as face_router
import os
import logging

# 初始化日志
setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境中应该限制具体的域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 启动时检查数据库连接
@app.on_event("startup")
async def startup_event():
    """应用启动时的初始化"""
    logger.info("🚀 TianMu智能服务器启动中...")
    

# OCR 路由
app.include_router(ocr_router, prefix="/ocr", tags=["OCR"])
# 人脸识别路由
app.include_router(face_router, prefix="/face", tags=["Face Recognition"])

# 健康检查
@app.get("/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "services": ["OCR", "Face Recognition"],
        "version": settings.VERSION
    }

# 根路径 - 返回测试界面
@app.get("/", tags=["Root"])
async def root():
    static_index = os.path.join(static_dir, "index.html")
    if os.path.exists(static_index):
        return FileResponse(static_index)
    else:
        return {
            "message": "TianMu Test API Server",
            "version": settings.VERSION,
            "available_services": [
                "/ocr - OCR文字识别",
                "/face - 人脸识别", 
                "/health - 健康检查",
                "/ - Web测试界面"
            ]
        }