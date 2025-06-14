#!/usr/bin/env python3
# 
#  - TianMu工业AGI试验台完美启动脚本
import sys
import os
import subprocess
from pathlib import Path

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
        "logs"
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
        "pydantic"
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
        print("请运行: pip install fastapi uvicorn psutil pydantic")
        return False
    
    return True

def start_server():
    """启动服务器"""
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
    
    # 检查主应用文件
    main_app = Path("app/main.py")
    if not main_app.exists():
        print("❌ 找不到 app/main.py 文件")
        print("请确保主应用文件存在")
        return False
    
    print("✅ app/main.py 文件存在")
    print()
    
    # 显示启动信息
    print("🎯 服务地址信息:")
    print("🌐 工业控制台: http://127.0.0.1:8000")
    print("🧠 AGI控制中心: http://127.0.0.1:8000/admin/login")
    print("🔑 管理密码: tianmu2025")
    print("📊 OCR接口: http://127.0.0.1:8000/ocr/table")
    print("🔒 生物识别: http://127.0.0.1:8000/face/register")
    print("📚 系统文档: http://127.0.0.1:8000/docs")
    print("🔍 健康监控: http://127.0.0.1:8000/health")
    print("📊 系统监控: http://127.0.0.1:8000/api/system-monitor")
    print()
    print("💡 提示:")
    print("  - 将工业界面HTML保存到: app/static/index.html")
    print("  - 按 Ctrl+C 停止服务器")
    print("🏭 " + "="*58 + " 🏭")
    print()
    
    # 使用uvicorn命令行启动，避免reload警告
    try:
        print("🚀 正在启动服务器...")
        cmd = [
            sys.executable,"app/main.py"
        ]
        
        # 启动服务器
        subprocess.run(cmd)
        
    except KeyboardInterrupt:
        print("\n\n🛑 服务器已停止")
        print("👋 感谢使用TianMu工业AGI试验台")
    except FileNotFoundError:
        print("❌ 找不到uvicorn，请安装: pip install uvicorn")
        return False
    except Exception as e:
        print(f"❌ 启动失败: {e}")
        return False
    
    return True

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