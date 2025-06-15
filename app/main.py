# app/main.py - 修复版本：解决重复初始化和局域网访问问题
import sys
import os
import socket
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
from fastapi.templating import Jinja2Templates
import logging
import psutil
import platform
from datetime import datetime
import asyncio
from typing import Dict, Any

# ========== 网络配置工具函数 ==========
def get_local_ip() -> str:
    """获取本机局域网IP地址"""
    try:
        # 创建UDP socket连接来获取本机IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        # 如果获取失败，尝试其他方法
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            if local_ip.startswith("127."):
                # 如果是回环地址，尝试获取所有网络接口
                import netifaces
                for interface in netifaces.interfaces():
                    addresses = netifaces.ifaddresses(interface)
                    if netifaces.AF_INET in addresses:
                        for addr in addresses[netifaces.AF_INET]:
                            ip = addr['addr']
                            if ip.startswith('192.168.') or ip.startswith('10.') or ip.startswith('172.'):
                                return ip
        except ImportError:
            pass
        return "192.168.1.100"  # 默认值

def get_all_local_ips() -> list:
    """获取所有本机IP地址"""
    ips = []
    try:
        # 获取所有网络接口
        for interface_name in socket.if_nameindex():
            interface = interface_name[1]
            try:
                addresses = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
                for addr in addresses:
                    ip = addr[4][0]
                    if not ip.startswith('127.') and ip not in ips:
                        ips.append(ip)
            except:
                continue
                
        # 备用方法
        if not ips:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            if not local_ip.startswith('127.'):
                ips.append(local_ip)
                
    except Exception as e:
        logging.warning(f"获取IP地址失败: {e}")
    
    return ips if ips else ["192.168.1.100"]

def check_port_available(port: int, host: str = "0.0.0.0") -> bool:
    """检查端口是否可用"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
            return True
    except OSError:
        return False

def find_available_port(start_port: int = 8000, end_port: int = 8100) -> int:
    """查找可用端口"""
    for port in range(start_port, end_port):
        if check_port_available(port):
            return port
    raise RuntimeError(f"无法找到可用端口 ({start_port}-{end_port})")

# ========== 确保必要目录存在 ==========
def ensure_directories():
    """确保所有必要的目录都存在"""
    directories = [
        "logs",
        "Data", 
        "Data/approval",
        "Data/approval/reports",
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

# ========== 全局服务实例（避免重复初始化）==========
admin_router = None
usage_tracker = None
ocr_router = None
face_router = None
approval_router = None

# 全局审批服务实例
approval_service_instance = None

# ========== 尝试导入模块 ==========
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

try:
    from app.routers.approval import router as approval_router
    # 创建全局审批服务实例
    from app.services.approval_service import ApprovalService
    approval_service_instance = ApprovalService()
    logger.info("✅ 实验审批系统已加载")
except ImportError as e:
    logger.warning(f"⚠️ 无法加载实验审批系统: {e}")

# ========== 应用初始化 ==========
app = FastAPI(
    title="TianMu工业AGI试验台",
    description="先进制造业人工通用智能平台 - 支持OCR识别、计算机视觉、智能分析、实验审批",
    version="2.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "工业接口", "description": "与上位机和工业设备的通信接口"},
        {"name": "AGI模块", "description": "人工通用智能核心功能"},
        {"name": "监控系统", "description": "实时监控和系统状态"},
        {"name": "管理后台", "description": "系统管理和配置界面"},
        {"name": "实验审批系统", "description": "局域网邮件审批流程"}
    ]
)

# ========== 局域网CORS中间件配置 ==========
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源（局域网内安全）
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== 模板引擎配置 ==========
templates = Jinja2Templates(directory="app/templates")

# ========== 静态文件配置 ==========
static_dir = Path("app/static")
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    logger.info(f"✅ 静态文件系统已启动: {static_dir}")
else:
    logger.warning(f"⚠️ 静态文件目录不存在: {static_dir}")

# ========== 路由注册 ==========
if admin_router:
    app.include_router(admin_router, tags=["管理后台"])
    logger.info("✅ 管理后台路由已注册")

if ocr_router:
    app.include_router(ocr_router, prefix="/ocr", tags=["工业接口"])
    logger.info("✅ OCR路由已注册")

if face_router:
    app.include_router(face_router, prefix="/face", tags=["工业接口"])
    logger.info("✅ 人脸识别路由已注册")

if approval_router:
    app.include_router(approval_router, tags=["实验审批系统"])
    logger.info("✅ 实验审批系统路由已注册")

# ========== 网络信息接口 ==========
@app.get("/api/network-info", summary="网络信息", tags=["监控系统"])
async def get_network_info():
    """获取服务器网络信息"""
    try:
        local_ips = get_all_local_ips()
        primary_ip = get_local_ip()
        
        return {
            "primary_ip": primary_ip,
            "all_ips": local_ips,
            "access_urls": [f"http://{ip}:8000" for ip in local_ips],
            "hostname": socket.gethostname(),
            "port": 8000,
            "network_interfaces": len(local_ips),
            "lan_access": True
        }
    except Exception as e:
        logger.error(f"获取网络信息失败: {e}")
        return {
            "primary_ip": "unknown",
            "all_ips": [],
            "access_urls": [],
            "hostname": "unknown",
            "port": 8000,
            "error": str(e)
        }

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
        local_ips = get_all_local_ips()
        return JSONResponse(content={
            "system": "TianMu工业AGI试验台",
            "version": "2.1.0",
            "status": "INTERFACE_MISSING",
            "message": "工业控制台界面文件不存在",
            "required_file": "app/static/index.html",
            "network_info": {
                "lan_ips": local_ips,
                "access_urls": [f"http://{ip}:8000" for ip in local_ips]
            },
            "services": {
                "AGI_CONTROL": "/admin/login" if admin_router else "未加载",
                "SYSTEM_DOCS": "/docs",
                "HEALTH_CHECK": "/health",
                "MONITORING": "/api/system-monitor",
                "OCR_SERVICE": "/ocr/table" if ocr_router else "未加载",
                "FACE_SERVICE": "/face/register" if face_router else "未加载",
                "APPROVAL_SERVICE": "/approval/test" if approval_router else "未加载",
                "NETWORK_INFO": "/api/network-info"
            },
            "setup_guide": [
                "1. 创建目录: mkdir -p app/static",
                "2. 将工业界面HTML保存到 app/static/index.html", 
                "3. 重启AGI试验台系统"
            ]
        })

# ========== 其他路由保持不变 ==========
@app.get("/api/public-stats", summary="生产统计数据", tags=["监控系统"])
async def get_production_stats():
    """获取生产线统计数据（公开接口）"""
    try:
        if usage_tracker:
            stats = await usage_tracker.get_statistics(hours=24)
            
            total_requests = stats.get("total_requests", 0)
            success_requests = stats.get("success_requests", 0)
            
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
        components = {
            "AGI_CORE": "OPERATIONAL",
            "ADMIN_PANEL": "OPERATIONAL" if admin_router else "NOT_LOADED",
            "OCR_ENGINE": "OPERATIONAL" if ocr_router else "NOT_LOADED", 
            "BIOMETRIC_SECURITY": "OPERATIONAL" if face_router else "NOT_LOADED",
            "USAGE_TRACKER": "OPERATIONAL" if usage_tracker else "NOT_LOADED",
            "APPROVAL_SYSTEM": "OPERATIONAL" if approval_router else "NOT_LOADED",
            "MONITORING_SYSTEM": "OPERATIONAL"
        }
        
        cpu_ok = psutil.cpu_percent() < 80
        memory_ok = psutil.virtual_memory().percent < 85
        
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
            "network_info": {
                "lan_ips": get_all_local_ips(),
                "primary_ip": get_local_ip(),
                "hostname": socket.gethostname()
            },
            "version": "2.1.0",
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

@app.get("/api/approval-stats", summary="审批系统统计", tags=["实验审批系统"])
async def get_approval_stats():
    """获取审批系统统计信息（公开接口）"""
    try:
        if approval_router and approval_service_instance:
            # 使用全局实例，避免重复初始化
            stats = await approval_service_instance.get_approval_statistics()
            
            return {
                "total_reports": stats.total_reports,
                "pending_approvals": stats.pending_approvals,
                "approved_reports": stats.approved_reports,
                "rejected_reports": stats.rejected_reports,
                "today_submissions": stats.today_submissions,
                "avg_approval_time_minutes": stats.avg_approval_time_minutes,
                "system_status": "OPERATIONAL",
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "system_status": "NOT_LOADED",
                "message": "审批系统未加载",
                "timestamp": datetime.now().isoformat()
            }
    except Exception as e:
        logger.error(f"[APPROVAL-STATS] 获取审批统计失败: {e}")
        return {
            "system_status": "ERROR",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

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
        # 网络配置信息
        local_ips = get_all_local_ips()
        primary_ip = get_local_ip()
        hostname = socket.gethostname()
        
        logger.info(f"[NETWORK] 主机名: {hostname}")
        logger.info(f"[NETWORK] 主IP地址: {primary_ip}")
        logger.info(f"[NETWORK] 所有IP地址: {', '.join(local_ips)}")
        
        # 初始化使用追踪系统
        if usage_tracker:
            await usage_tracker.initialize()
            logger.info("[STARTUP] ✅ 数据追踪系统已启动")
        else:
            logger.warning("[STARTUP] ⚠️ 数据追踪系统未加载")
        
        # 初始化审批系统（使用全局实例）
        if approval_router and approval_service_instance:
            try:
                await approval_service_instance._ensure_cache_initialized()
                logger.info("[STARTUP] ✅ 实验审批系统已启动")
            except Exception as e:
                logger.warning(f"[STARTUP] ⚠️ 审批系统初始化失败: {e}")
        
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
        if approval_router:
            loaded_modules.append("实验审批")
        if usage_tracker:
            loaded_modules.append("使用追踪")
        
        logger.info(f"[STARTUP] ✅ 已加载模块: {', '.join(loaded_modules) if loaded_modules else '基础模块'}")
        
        # 启动完成
        logger.info("=" * 60)
        logger.info("[ACCESS] 🌐 局域网访问地址:")
        for ip in local_ips:
            logger.info(f"[ACCESS]    http://{ip}:8000")
        logger.info("=" * 60)
        logger.info("[ENDPOINTS] 可用服务端点:")
        if admin_router:
            logger.info("[ENDPOINTS] 🧠 AGI控制中心: /admin/login")
        if ocr_router:
            logger.info("[ENDPOINTS] 📊 OCR接口: /ocr/table")
        if face_router:
            logger.info("[ENDPOINTS] 🔒 生物识别: /face/register")
        if approval_router:
            logger.info("[ENDPOINTS] 📋 实验审批: /approval/test")
        logger.info("[ENDPOINTS] 📚 系统文档: /docs")
        logger.info("[ENDPOINTS] 🔍 健康监控: /health")
        logger.info("[ENDPOINTS] 📊 系统监控: /api/system-monitor")
        logger.info("[ENDPOINTS] 🌐 网络信息: /api/network-info")
        if approval_router:
            logger.info("[ENDPOINTS] 📈 审批统计: /api/approval-stats")
        logger.info("=" * 60)
        logger.info("[SYSTEM] 🚀 TianMu工业AGI试验台启动完成")
        logger.info("[SYSTEM] 🔗 局域网内其他设备可通过以上地址访问")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"[STARTUP] ❌ 系统启动失败: {e}")
        logger.info("[STARTUP] 🔄 系统将以基础模式继续运行")

@app.on_event("shutdown")
async def shutdown_industrial_system():
    """工业AGI系统关闭"""
    logger.info("[SHUTDOWN] 🛑 TianMu工业AGI试验台正在关闭...")
    
    if approval_router:
        try:
            from app.services.pdf_generator import PDFGenerator
            pdf_generator = PDFGenerator()
            cleaned = pdf_generator.cleanup_old_pdfs(days=7)
            logger.info(f"[SHUTDOWN] 🧹 清理了 {cleaned} 个旧PDF文件")
        except Exception as e:
            logger.warning(f"[SHUTDOWN] ⚠️ 清理PDF文件失败: {e}")
    
    logger.info("[SHUTDOWN] 💾 保存系统状态...")
    logger.info("[SHUTDOWN] ✅ 系统已安全关闭")

# ========== 异常处理 ==========
@app.exception_handler(404)
async def industrial_not_found_handler(request, exc):
    """工业级404处理"""
    logger.warning(f"[404] 未找到资源: {request.url.path}")
    
    available_endpoints = ["/", "/health", "/docs", "/api/system-monitor", "/api/network-info"]
    if admin_router:
        available_endpoints.append("/admin/login")
    if ocr_router:
        available_endpoints.append("/ocr/table")
    if face_router:
        available_endpoints.append("/face/register")
    if approval_router:
        available_endpoints.extend(["/approval/test", "/approval/submit_report"])
    
    return JSONResponse(
        status_code=404,
        content={
            "error": "RESOURCE_NOT_FOUND",
            "path": str(request.url.path),
            "system": "TianMu工业AGI试验台",
            "available_endpoints": available_endpoints,
            "network_info": {
                "lan_access": True,
                "primary_ip": get_local_ip(),
                "all_access_urls": [f"http://{ip}:8000" for ip in get_all_local_ips()]
            },
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
    
    # 获取网络信息
    local_ips = get_all_local_ips()
    primary_ip = get_local_ip()
    hostname = socket.gethostname()
    
    # 查找可用端口
    try:
        port = find_available_port()
    except RuntimeError:
        port = 8000
        print("⚠️ 无法找到可用端口，使用默认端口8000（可能被占用）")
    
    print("🏭 " + "="*70 + " 🏭")
    print("🚀 启动TianMu工业级AGI试验台 - 局域网版本")
    print("🏭 " + "="*70 + " 🏭")
    print()
    print(f"🖥️  主机信息: {hostname}")
    print(f"🌐 主IP地址: {primary_ip}")
    print(f"📡 服务端口: {port}")
    print()
    print("🔗 局域网访问地址:")
    for ip in local_ips:
        print(f"   http://{ip}:{port}")
    print()
    print("📋 可用服务:")
    print(f"   🌐 工业控制台: http://{primary_ip}:{port}")
    if admin_router:
        print(f"   🧠 AGI控制中心: http://{primary_ip}:{port}/admin/login")
        print(f"   🔑 管理密码: tianmu2025")
    if ocr_router:
        print(f"   📊 OCR接口: http://{primary_ip}:{port}/ocr/table")
    if face_router:
        print(f"   🔒 生物识别: http://{primary_ip}:{port}/face/register")
    if approval_router:
        print(f"   📋 实验审批: http://{primary_ip}:{port}/approval/test")
    print(f"   📚 系统文档: http://{primary_ip}:{port}/docs")
    print(f"   🔍 健康监控: http://{primary_ip}:{port}/health")
    print(f"   📊 系统监控: http://{primary_ip}:{port}/api/system-monitor")
    print(f"   🌐 网络信息: http://{primary_ip}:{port}/api/network-info")
    if approval_router:
        print(f"   📈 审批统计: http://{primary_ip}:{port}/api/approval-stats")
    print()
    print("💡 局域网配置说明:")
    print("   • 服务绑定到 0.0.0.0，局域网内所有设备可访问")
    print("   • 确保防火墙允许端口访问")
    print("   • 审批系统仅限内网IP访问，安全可靠")
    print("   • 支持手机、平板、电脑等多设备访问")
    print()
    print("🏭 " + "="*70 + " 🏭")
    
    # 启动服务器 - 绑定到所有接口
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",        # 关键：绑定到所有网络接口
        port=port,
        reload=False,          # 生产环境禁用reload
        log_level="info",
        access_log=True,
        server_header=False,   # 隐藏服务器头信息
        date_header=False      # 隐藏日期头信息
    )