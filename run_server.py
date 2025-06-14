#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TianMu智能服务器启动脚本
"""
import os
import sys
import uvicorn
import webbrowser
import threading
import time
from pathlib import Path

def start_server():
    """启动FastAPI服务器"""
    # 添加项目路径到sys.path
    project_root = Path(__file__).parent
    sys.path.insert(0, str(project_root))
    
    # 设置环境变量
    os.environ.setdefault("PYTHONPATH", str(project_root))
    
    print("🚀 TianMu智能服务器启动中...")
    print(f"📁 项目路径: {project_root}")
    print("🌐 服务地址: http://127.0.0.1:8000")
    print("📋 API文档: http://127.0.0.1:8000/docs")
    print("=" * 50)
    
    # 延迟打开浏览器
    def open_browser():
        time.sleep(2)  # 等待服务器启动
        webbrowser.open("http://127.0.0.1:8000")
    
    browser_thread = threading.Thread(target=open_browser)
    browser_thread.daemon = True
    browser_thread.start()
    
    try:
        # 启动服务器
        uvicorn.run(
            "app.main:app",
            host="127.0.0.1",
            port=8000,
            reload=False,  # 生产环境不需要热重载
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n👋 服务器已停止")
    except Exception as e:
        print(f"❌ 服务器启动失败: {e}")
        input("按回车键退出...")

if __name__ == "__main__":
    start_server()