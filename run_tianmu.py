#!/usr/bin/env python3
# 
# run_tianmu.py - TianMu工业AGI试验台完美启动脚本 - 集成工况识别
import sys
import os
import subprocess
import time
import signal
import threading
from pathlib import Path
import socket

def ensure_structure():
    """确保项目结构完整"""
    # 必要的目录
    directories = [
        "app",
        "app/routers", 
        "app/services",
        "app/schemas",
        "app/utils",
        "app/static",
        "app/templates",
        "Data",
        "logs",
        "mcp_server"  # MCP服务器独立目录
    ]
    
    # 必要的__init__.py文件
    init_files = [
        "app/__init__.py",
        "app/routers/__init__.py",
        "app/services/__init__.py", 
        "app/schemas/__init__.py",
        "app/utils/__init__.py"
    ]
    
    print("🔧 检查项目结构...")
    
    # 创建目录
    for directory in directories:
        Path(directory).mkdir(parents=True, exist_ok=True)
        print(f"  ✅ {directory}/")
    
    # 创建__init__.py文件
    for init_file in init_files:
        init_path = Path(init_file)
        if not init_path.exists():
            init_path.touch()
            print(f"  ✅ {init_file}")
        else:
            print(f"  ✓ {init_file}")

def check_requirements():
    """检查必要的依赖"""
    required_packages = [
        "fastapi",
        "uvicorn", 
        "psutil",
        "pydantic",
        "httpx"  # 工况识别需要
    ]
    
    print("📦 检查依赖包...")
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
            print(f"  ✅ {package}")
        except ImportError:
            print(f"  ❌ {package} - 缺失")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n⚠️ 缺少依赖: {', '.join(missing_packages)}")
        print("请运行: pip install fastapi uvicorn psutil pydantic httpx")
        return False
    
    return True

def create_missing_services():
    """创建缺失的服务文件"""
    
    # 创建简单的使用追踪器（如果不存在）
    usage_tracker_file = Path("app/services/usage_tracker.py")
    if not usage_tracker_file.exists():
        usage_tracker_content = '''# app/services/usage_tracker.py
import logging
from typing import Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class UsageTracker:
    def __init__(self):
        self.stats = {"total_requests": 0, "success_requests": 0}
    
    async def initialize(self):
        logger.info("使用追踪器已初始化")
    
    async def get_statistics(self, hours: int = 24) -> Dict[str, Any]:
        return self.stats

def track_usage_simple(operation: str):
    """简单的使用追踪装饰器"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                raise e
        return wrapper
    return decorator

# 全局实例
usage_tracker = UsageTracker()
'''
        usage_tracker_file.write_text(usage_tracker_content, encoding='utf-8')
        print(f"  ✅ 创建了使用追踪器: {usage_tracker_file}")

def check_port_available(port: int, host: str = "127.0.0.1") -> bool:
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

def start_mcp_server():
    """启动MCP服务器"""
    print("🔧 启动MCP工具服务器...")
    
    # 检查MCP服务器文件
    mcp_main = Path("app/mcp_server/main.py")
    if not mcp_main.exists():
        print(f"  ⚠️ MCP服务器文件不存在: {mcp_main}")
        print("  💡 MCP服务器是可选的，系统将继续运行")
        return None
    
    # 查找MCP可用端口
    try:
        mcp_port = find_available_port(8001, 8050)
    except RuntimeError:
        print("  ❌ 无法为MCP服务器找到可用端口")
        return None
    
    try:
        # 设置环境变量
        env = os.environ.copy()
        env['MCP_PORT'] = str(mcp_port)
        
        # 启动MCP服务器进程
        mcp_process = subprocess.Popen(
            [sys.executable, str(mcp_main)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # 等待服务器启动
        time.sleep(2)
        
        # 检查进程是否还在运行
        if mcp_process.poll() is None:
            print(f"  ✅ MCP服务器已启动 (PID: {mcp_process.pid}, Port: {mcp_port})")
            return mcp_process
        else:
            stdout, stderr = mcp_process.communicate(timeout=1)
            print(f"  ❌ MCP服务器启动失败")
            if stderr:
                print(f"      错误: {stderr}")
            return None
            
    except Exception as e:
        print(f"  ❌ MCP服务器启动异常: {e}")
        return None

def start_server():
    """启动主服务器"""
    print("🏭 " + "="*58 + " 🏭")
    print("🚀 TianMu工业AGI试验台启动程序")
    print("🏭 " + "="*58 + " 🏭")
    print()
    
    # 检查项目结构
    ensure_structure()
    print()
    
    # 检查依赖
    if not check_requirements():
        return False
    print()
    
    # 创建缺失的服务文件
    create_missing_services()
    print()
    
    # 启动MCP服务器（可选）
    mcp_process = start_mcp_server()
    print()
    
    # 检查主应用文件
    main_app = Path("app/main.py")
    if not main_app.exists():
        print("❌ 找不到 app/main.py 文件")
        print("请确保主应用文件存在")
        return False
    
    print("✅ app/main.py 文件存在")
    print()
    
    # 获取网络信息
    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        if local_ip.startswith('127.'):
            local_ip = "192.168.1.100"  # 默认值
    except:
        hostname = "localhost"
        local_ip = "192.168.1.100"
    
    # 显示启动信息
    print("🎯 服务地址信息:")
    print("🌐 工业控制台: http://127.0.0.1:8000")
    print(f"🌐 局域网访问: http://{local_ip}:8000")
    print("🧠 AGI控制中心: http://127.0.0.1:8000/admin/login")
    print("🔑 管理密码: tianmu2025")
    print("📊 OCR接口: http://127.0.0.1:8000/ocr/table")
    print("🔒 生物识别: http://127.0.0.1:8000/face/register")
    print("📚 系统文档: http://127.0.0.1:8000/docs")
    print("🔍 健康监控: http://127.0.0.1:8000/health")
    print("📊 系统监控: http://127.0.0.1:8000/api/system-monitor")
    
    # 新增工况识别功能
    print()
    print("🏭 工况识别功能:")
    print("🔬 工况识别状态: http://127.0.0.1:8000/workload/status")
    print("🧪 工况识别测试: http://127.0.0.1:8000/workload/test")
    print("🔄 LLM切换接口: http://127.0.0.1:8000/workload/llm/switch")
    print("🚀 Cerebras状态: http://127.0.0.1:8000/cerebras/status")
    
    if mcp_process:
        print()
        print("🔧 MCP工具服务器:")
        print("🛠️ MCP服务状态: http://127.0.0.1:8001/health")
        print("📋 MCP工具列表: http://127.0.0.1:8001/tools/list")
    
    print()
    print("💡 提示:")
    print("  - 将工业界面HTML保存到: app/static/index.html")
    print("  - 工况识别支持Qwen3 + Cerebras多LLM")
    print("  - MCP服务器提供单位转换和物理校验")
    print("  - 按 Ctrl+C 停止服务器")
    print("🏭 " + "="*58 + " 🏭")
    print()
    
    # 设置信号处理
    def signal_handler(signum, frame):
        print("\n\n🛑 正在停止服务器...")
        if mcp_process and mcp_process.poll() is None:
            print("🔧 停止MCP服务器...")
            try:
                mcp_process.terminate()
                mcp_process.wait(timeout=5)
                print("✅ MCP服务器已停止")
            except subprocess.TimeoutExpired:
                mcp_process.kill()
                print("🔪 强制终止MCP服务器")
            except Exception as e:
                print(f"⚠️ 停止MCP服务器时出错: {e}")
        print("👋 感谢使用TianMu工业AGI试验台")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 使用python直接运行，而不是uvicorn命令行
    try:
        print("🚀 正在启动主服务器...")
        
        # 直接运行main.py
        result = subprocess.run([sys.executable, "app/main.py"], check=False)
        
        # 如果主服务器退出，清理MCP服务器
        if mcp_process and mcp_process.poll() is None:
            mcp_process.terminate()
        
        return result.returncode == 0
        
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)
    except FileNotFoundError:
        print("❌ 找不到Python解释器")
        return False
    except Exception as e:
        print(f"❌ 启动失败: {e}")
        return False

def main():
    """主函数"""
    try:
        success = start_server()
        if not success:
            input("\n按回车键退出...")
            sys.exit(1)
    except Exception as e:
        print(f"❌ 启动脚本失败: {e}")
        input("\n按回车键退出...")
        sys.exit(1)

if __name__ == "__main__":
    main()