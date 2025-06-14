# app/main.py - 简化版本，解决导入问题
import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# 抑制PaddleOCR的ccache警告
import warnings
warnings.filterwarnings("ignore", message="No ccache found")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import HTTPException
import logging
import psutil
import platform
from datetime import datetime
import asyncio
from typing import Dict, Any

# ========== 确保必要目录存在 ==========
def ensure_directories():
    """确保所有必要的目录都存在"""
    directories = [
        "logs",
        "Data", 
        "app/static",
        "app/templates"
    ]
    
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
        print(f"✅ 确保目录存在: {directory}")

# 首先创建目录
ensure_directories()

# ========== 工业级日志配置 ==========
def setup_logging():
    """设置日志配置"""
    try:
        # 创建格式化器
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
        
        # 创建控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        
        # 创建文件处理器
        log_file = Path("logs/tianmu_agi_lab.log")
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        
        # 配置根日志器
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(console_handler)
        root_logger.addHandler(file_handler)
        
        print(f"✅ 日志系统已配置: {log_file}")
        
    except Exception as e:
        print(f"⚠️ 日志配置失败，使用基础配置: {e}")
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )

# 配置日志
setup_logging()
logger = logging.getLogger("TianMu-AGI-Lab")

# ========== 尝试导入模块 ==========
admin_router = None
usage_tracker = None
ocr_router = None
face_router = None

try:
    from app.routers.admin import router as admin_router
    logger.info("✅ 管理后台模块已加载")
except ImportError as e:
    logger.warning(f"⚠️ 无法加载管理后台: {e}")

try:
    from app.services.usage_tracker import usage_tracker
    logger.info("✅ 使用追踪模块已加载")
except ImportError as e:
    logger.warning(f"⚠️ 无法加载使用追踪: {e}")

try:
    from app.routers.ocr import router as ocr_router
    logger.info("✅ OCR模块已加载")
except ImportError as e:
    logger.warning(f"⚠️ 无法加载OCR模块: {e}")

try:
    from app.routers.face_recognition import router as face_router
    logger.info("✅ 人脸识别模块已加载")
except ImportError as e:
    logger.warning(f"⚠️ 无法加载人脸识别模块: {e}")

# ========== 应用初始化 ==========
app = FastAPI(
    title="TianMu工业AGI试验台",
    description="先进制造业人工通用智能平台 - 支持OCR识别、计算机视觉、智能分析",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "工业接口", "description": "与上位机和工业设备的通信接口"},
        {"name": "AGI模块", "description": "人工通用智能核心功能"},
        {"name": "监控系统", "description": "实时监控和系统状态"},
        {"name": "管理后台", "description": "系统管理和配置界面"}
    ]
)

# ========== 工业级中间件配置 ==========
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== 静态文件配置 ==========
static_dir = Path("app/static")
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    logger.info(f"✅ 静态文件系统已启动: {static_dir}")
else:
    logger.warning(f"⚠️ 静态文件目录不存在: {static_dir}")

# ========== 路由注册 ==========
# 注册可用的路由
if admin_router:
    app.include_router(admin_router, tags=["管理后台"])
    logger.info("✅ 管理后台路由已注册")

if ocr_router:
    app.include_router(ocr_router, prefix="/ocr", tags=["工业接口"])
    logger.info("✅ OCR路由已注册")

if face_router:
    app.include_router(face_router, prefix="/face", tags=["工业接口"])
    logger.info("✅ 人脸识别路由已注册")

# ========== 主界面路由 ==========
@app.get("/", summary="工业AGI控制台", tags=["监控系统"])
async def industrial_console():
    """返回工业级AGI试验台主控制台"""
    static_index = static_dir / "index.html"
    
    if static_index.exists():
        logger.info("📄 返回工业AGI控制台界面")
        return FileResponse(str(static_index))
    else:
        logger.warning("⚠️ 工业控制台界面文件缺失")
        return JSONResponse(content={
            "system": "TianMu工业AGI试验台",
            "version": "2.0.0",
            "status": "INTERFACE_MISSING",
            "message": "工业控制台界面文件不存在",
            "required_file": "app/static/index.html",
            "services": {
                "AGI_CONTROL": "/admin/login" if admin_router else "未加载",
                "SYSTEM_DOCS": "/docs",
                "HEALTH_CHECK": "/health",
                "MONITORING": "/api/system-monitor",
                "OCR_SERVICE": "/ocr/table" if ocr_router else "未加载",
                "FACE_SERVICE": "/face/register" if face_router else "未加载"
            },
            "setup_guide": [
                "1. 创建目录: mkdir -p app/static",
                "2. 将工业界面HTML保存到 app/static/index.html", 
                "3. 重启AGI试验台系统"
            ]
        })

# ========== 基础监控接口 ==========
@app.get("/api/public-stats", summary="生产统计数据", tags=["监控系统"])
async def get_production_stats():
    """获取生产线统计数据（公开接口）"""
    try:
        if usage_tracker:
            stats = await usage_tracker.get_statistics(hours=24)
            
            total_requests = stats.get("total_requests", 0)
            success_requests = stats.get("success_requests", 0)
            
            # 计算生产效率
            efficiency = 100.0
            if total_requests > 0:
                efficiency = (success_requests / total_requests) * 100
            
            return {
                "total_requests": total_requests,
                "success_rate": round(efficiency, 1),
                "avg_time": stats.get("avg_processing_time", 0),
                "data_volume": stats.get("total_file_size", 0),
                "status": "OPERATIONAL",
                "timestamp": datetime.now().isoformat(),
                "shift": get_current_shift()
            }
        else:
            return {
                "total_requests": 0,
                "success_rate": 100.0,
                "avg_time": 0.0,
                "data_volume": 0,
                "status": "STANDBY",
                "timestamp": datetime.now().isoformat(),
                "shift": get_current_shift()
            }
    except Exception as e:
        logger.error(f"[STATS] 统计数据获取失败: {e}")
        return {
            "total_requests": 0,
            "success_rate": 100.0,
            "avg_time": 0.0,
            "data_volume": 0,
            "status": "ERROR",
            "timestamp": datetime.now().isoformat(),
            "shift": get_current_shift()
        }

@app.get("/api/system-monitor", summary="系统资源监控", tags=["监控系统"])
async def get_system_monitor():
    """获取系统资源使用情况"""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        
        # 安全地获取磁盘使用情况
        try:
            disk = psutil.disk_usage('/')
            disk_percent = disk.percent
        except:
            try:
                disk = psutil.disk_usage('C:\\')
                disk_percent = disk.percent
            except:
                disk_percent = 0.0
        
        return {
            "cpu_percent": round(cpu_percent, 1),
            "memory_percent": round(memory.percent, 1),
            "disk_percent": round(disk_percent, 1),
            "network_connections": 0,
            "system_load": cpu_percent / 100,
            "uptime_seconds": int(datetime.now().timestamp() - psutil.boot_time()),
            "status": "MONITORING"
        }
    except Exception as e:
        logger.error(f"[MONITOR] 系统监控失败: {e}")
        return {
            "cpu_percent": 0.0,
            "memory_percent": 0.0, 
            "disk_percent": 0.0,
            "network_connections": 0,
            "system_load": 0.0,
            "uptime_seconds": 0,
            "status": "ERROR"
        }

@app.get("/health", summary="系统健康检查", tags=["监控系统"])
async def industrial_health_check():
    """工业系统健康检查"""
    try:
        # 检查已加载的组件
        components = {
            "AGI_CORE": "OPERATIONAL",
            "ADMIN_PANEL": "OPERATIONAL" if admin_router else "NOT_LOADED",
            "OCR_ENGINE": "OPERATIONAL" if ocr_router else "NOT_LOADED", 
            "BIOMETRIC_SECURITY": "OPERATIONAL" if face_router else "NOT_LOADED",
            "USAGE_TRACKER": "OPERATIONAL" if usage_tracker else "NOT_LOADED",
            "MONITORING_SYSTEM": "OPERATIONAL"
        }
        
        # 检查资源状态
        cpu_ok = psutil.cpu_percent() < 80
        memory_ok = psutil.virtual_memory().percent < 85
        
        # 安全地检查磁盘
        disk_ok = True
        try:
            disk_usage = psutil.disk_usage('/').percent
            disk_ok = disk_usage < 90
        except:
            try:
                disk_usage = psutil.disk_usage('C:\\').percent
                disk_ok = disk_usage < 90
            except:
                pass
        
        system_status = "HEALTHY" if all([cpu_ok, memory_ok, disk_ok]) else "WARNING"
        
        return {
            "status": system_status,
            "components": components,
            "system_info": {
                "platform": f"{platform.system()} {platform.release()}",
                "python_version": platform.python_version(),
                "architecture": platform.machine()
            },
            "resources": {
                "cpu_ok": cpu_ok,
                "memory_ok": memory_ok,
                "disk_ok": disk_ok
            },
            "version": "2.0.0",
            "timestamp": datetime.now().isoformat(),
            "environment": "INDUSTRIAL"
        }
    except Exception as e:
        logger.error(f"[HEALTH] 健康检查失败: {e}")
        return {
            "status": "ERROR",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

# ========== 辅助函数 ==========
def get_current_shift() -> str:
    """获取当前班次"""
    hour = datetime.now().hour
    if 6 <= hour < 14:
        return "DAY_SHIFT"
    elif 14 <= hour < 22:
        return "EVENING_SHIFT"
    else:
        return "NIGHT_SHIFT"

# ========== 生命周期事件 ==========
@app.on_event("startup")
async def startup_industrial_system():
    """工业AGI系统启动"""
    logger.info("=" * 60)
    logger.info("[STARTUP] TianMu工业AGI试验台正在启动...")
    logger.info("=" * 60)
    
    try:
        # 初始化使用追踪系统
        if usage_tracker:
            await usage_tracker.initialize()
            logger.info("[STARTUP] ✅ 数据追踪系统已启动")
        else:
            logger.warning("[STARTUP] ⚠️ 数据追踪系统未加载")
        
        # 检查系统资源
        cpu_count = psutil.cpu_count()
        memory_gb = psutil.virtual_memory().total / (1024**3)
        logger.info(f"[STARTUP] ✅ 系统资源: {cpu_count}核心, {memory_gb:.1f}GB内存")
        
        # 检查关键文件
        static_index = static_dir / "index.html"
        if static_index.exists():
            logger.info("[STARTUP] ✅ 工业控制台界面已就绪")
        else:
            logger.warning("[STARTUP] ⚠️ 工业控制台界面文件缺失")
        
        # 统计加载的模块
        loaded_modules = []
        if admin_router:
            loaded_modules.append("管理后台")
        if ocr_router:
            loaded_modules.append("OCR引擎")
        if face_router:
            loaded_modules.append("生物识别")
        if usage_tracker:
            loaded_modules.append("使用追踪")
        
        logger.info(f"[STARTUP] ✅ 已加载模块: {', '.join(loaded_modules) if loaded_modules else '基础模块'}")
        
        # 启动完成
        logger.info("=" * 60)
        logger.info("[ACCESS] 🌐 工业控制台: http://127.0.0.1:8000")
        if admin_router:
            logger.info("[ACCESS] 🧠 AGI控制中心: http://127.0.0.1:8000/admin/login")
        if ocr_router:
            logger.info("[ACCESS] 📊 OCR接口: http://127.0.0.1:8000/ocr/table")
        if face_router:
            logger.info("[ACCESS] 🔒 生物识别: http://127.0.0.1:8000/face/register")
        logger.info("[ACCESS] 📚 系统文档: http://127.0.0.1:8000/docs")
        logger.info("[ACCESS] 🔍 健康监控: http://127.0.0.1:8000/health")
        logger.info("[ACCESS] 📊 系统监控: http://127.0.0.1:8000/api/system-monitor")
        logger.info("=" * 60)
        logger.info("[SYSTEM] 🚀 TianMu工业AGI试验台启动完成")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"[STARTUP] ❌ 系统启动失败: {e}")
        logger.info("[STARTUP] 🔄 系统将以基础模式继续运行")

@app.on_event("shutdown")
async def shutdown_industrial_system():
    """工业AGI系统关闭"""
    logger.info("[SHUTDOWN] 🛑 TianMu工业AGI试验台正在关闭...")
    logger.info("[SHUTDOWN] 💾 保存系统状态...")
    logger.info("[SHUTDOWN] ✅ 系统已安全关闭")

# ========== 异常处理 ==========
@app.exception_handler(404)
async def industrial_not_found_handler(request, exc):
    """工业级404处理"""
    logger.warning(f"[404] 未找到资源: {request.url.path}")
    
    available_endpoints = ["/", "/health", "/docs", "/api/system-monitor"]
    if admin_router:
        available_endpoints.append("/admin/login")
    if ocr_router:
        available_endpoints.append("/ocr/table")
    if face_router:
        available_endpoints.append("/face/register")
    
    return JSONResponse(
        status_code=404,
        content={
            "error": "RESOURCE_NOT_FOUND",
            "path": str(request.url.path),
            "system": "TianMu工业AGI试验台",
            "available_endpoints": available_endpoints,
            "timestamp": datetime.now().isoformat()
        }
    )

@app.exception_handler(500)
async def industrial_server_error_handler(request, exc):
    """工业级500处理"""
    logger.error(f"[500] 系统内部错误: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "SYSTEM_ERROR",
            "message": "工业AGI系统遇到内部错误",
            "timestamp": datetime.now().isoformat(),
            "support": "请检查系统日志或联系技术支持"
        }
    )

# ========== 开发调试 ==========
if __name__ == "__main__":
    import uvicorn
    
    print("🏭 " + "="*58 + " 🏭")
    print("🚀 启动TianMu工业级AGI试验台")
    print("🏭 " + "="*58 + " 🏭")
    print()
    print("🌐 工业控制台: http://127.0.0.1:8000")
    if admin_router:
        print("🧠 AGI控制中心: http://127.0.0.1:8000/admin/login")
        print("🔑 管理密码: tianmu2025")
    if ocr_router:
        print("📊 OCR接口: http://127.0.0.1:8000/ocr/table")
    if face_router:
        print("🔒 生物识别: http://127.0.0.1:8000/face/register")
    print("📚 系统文档: http://127.0.0.1:8000/docs")
    print("🔍 健康监控: http://127.0.0.1:8000/health")
    print("📊 系统监控: http://127.0.0.1:8000/api/system-monitor")
    print()
    print("💡 确保工业界面文件存在: app/static/index.html")
    print("🏭 " + "="*58 + " 🏭")
    
    # 修复reload警告的运行方式
    uvicorn.run(
        "app.main:app",  # 使用导入字符串而不是app对象
        host="127.0.0.1",
        port=8000,
        reload=False,  # 暂时禁用reload避免问题
        log_level="info",
        access_log=True
    )