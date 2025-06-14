#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TianMu智能服务器打包脚本
使用PyInstaller将项目打包成exe文件
"""
import os
import sys
import shutil
import subprocess
from pathlib import Path

def build_exe():
    """打包成exe文件"""
    print("🔨 开始打包TianMu智能服务器...")
    
    # 项目根目录
    project_root = Path(__file__).parent
    dist_dir = project_root / "dist"
    build_dir = project_root / "build"
    
    # 清理之前的构建
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
        print("🧹 清理旧的构建文件")
    
    if build_dir.exists():
        shutil.rmtree(build_dir)
    
    # 询问用户是否包含数据库文件
    include_database = input("是否将数据库文件打包到exe中？(y/n，默认n): ").strip().lower()
    
    # PyInstaller参数
    pyinstaller_args = [
        "pyinstaller",
        "--onefile",                          # 打包成单个exe文件
        "--console",                          # 显示控制台（便于调试）
        "--name=TianMu智能服务器",             # exe文件名
        "--icon=app/static/favicon.ico",      # 图标文件（如果有的话）
        "--add-data=app;app",                 # 包含app目录
        "--hidden-import=uvicorn",            # 隐式导入
        "--hidden-import=uvicorn.lifespan",
        "--hidden-import=uvicorn.lifespan.on",
        "--hidden-import=uvicorn.protocols",
        "--hidden-import=uvicorn.protocols.websockets",
        "--hidden-import=uvicorn.protocols.http",
        "--hidden-import=uvicorn.protocols.http.auto",
        "--hidden-import=uvicorn.protocols.websockets.auto",
        "--hidden-import=uvicorn.loops",
        "--hidden-import=uvicorn.loops.auto",
        "--hidden-import=paddleocr",
        "--hidden-import=paddlepaddle",
        "--hidden-import=face_recognition",
        "--hidden-import=cv2",
        "--hidden-import=pyodbc",
        "--hidden-import=sqlite3",
        "--paths=.",                          # 添加当前路径
        "run_server.py"                       # 入口文件
    ]
    
    # 根据用户选择决定是否包含数据库
    if include_database == 'y':
        if (project_root / "Data").exists():
            pyinstaller_args.insert(-1, "--add-data=Data;Data")
            print("📁 将包含Data目录到exe中")
        else:
            print("⚠️ Data目录不存在，跳过打包数据库文件")
    else:
        print("📋 不包含数据库文件，程序将从外部路径读取")
    
    # 如果没有图标文件，移除图标参数
    if not (project_root / "app/static/favicon.ico").exists():
        pyinstaller_args = [arg for arg in pyinstaller_args if not arg.startswith("--icon")]
    
    try:
        print("📦 正在执行PyInstaller...")
        print(f"命令: {' '.join(pyinstaller_args)}")
        
        result = subprocess.run(pyinstaller_args, check=True, capture_output=True, text=True)
        
        print("✅ 打包成功!")
        print(f"📁 exe文件位置: {dist_dir / 'TianMu智能服务器.exe'}")
        
        # 复制必要文件到dist目录
        exe_dir = dist_dir / "TianMu智能服务器_Portable"
        exe_dir.mkdir(exist_ok=True)
        
        # 复制exe文件
        exe_source = dist_dir / "TianMu智能服务器.exe"
        exe_target = exe_dir / "TianMu智能服务器.exe"
        if exe_source.exists():
            shutil.copy2(exe_source, exe_target)
        
        # 复制数据库文件（如果用户选择包含）
        if include_database == 'y' and (project_root / "Data").exists():
            shutil.copytree(project_root / "Data", exe_dir / "Data", dirs_exist_ok=True)
            print("📁 已复制数据库文件到便携版")
        
        # 创建数据库配置示例文件
        config_content = f"""# TianMu智能服务器数据库配置文件
# 请根据实际情况修改数据库路径

# 方式1: 直接指定完整路径
D:\\demoTest\\IntelligentFactoryDemo\\TianMuTest\\TianMuTest\\Data\\SoftWareParam.mdb

# 方式2: 使用环境变量格式
# ACCESS_DB_PATH=D:\\demoTest\\IntelligentFactoryDemo\\TianMuTest\\TianMuTest\\Data\\SoftWareParam.mdb

# 注意：
# 1. 路径中的反斜杠需要使用双反斜杠 \\\\
# 2. 或者使用正斜杠 /
# 3. 确保数据库文件确实存在于指定路径
# 4. 如果使用相对路径，相对于exe文件所在目录

# 示例路径：
# D:/IntelligentFactory/Data/SoftWareParam.mdb
# ./Data/SoftWareParam.mdb
# ../SharedData/SoftWareParam.mdb
"""
        
        config_file = exe_dir / "database_config.txt"
        with open(config_file, "w", encoding="utf-8") as f:
            f.write(config_content)
        
        # 创建启动说明
        readme_content = f"""
TianMu智能服务器 - 使用说明
=========================

🚀 快速启动：
1. 双击 "TianMu智能服务器.exe" 启动服务器
2. 系统会自动打开浏览器访问测试界面
3. 如果浏览器没有自动打开，请手动访问: http://127.0.0.1:8000

📁 数据库配置：
{'✅ 数据库文件已包含在程序中，无需额外配置' if include_database == 'y' else '''
❗ 需要配置数据库路径：
1. 编辑 database_config.txt 文件
2. 修改第4行的数据库路径为实际路径
3. 保存文件后重启程序

上位机数据库路径示例：
D:\\demoTest\\IntelligentFactoryDemo\\TianMuTest\\TianMuTest\\Data\\SoftWareParam.mdb
'''}

🔧 功能说明:
- OCR表格识别: 上传图片进行文字识别
- 人脸识别: 支持人脸注册、识别、检测等功能
- Web界面: 提供直观的测试和管理界面

⚠️ 注意事项:
- 请确保数据库文件路径正确且可访问
- 首次运行可能需要较长时间加载AI模型
- 如有问题请查看控制台输出的错误信息
- 建议关闭杀毒软件的实时监控以提升性能

🆘 故障排除:
1. 数据库连接失败：检查database_config.txt中的路径
2. 端口被占用：修改程序端口或关闭占用程序
3. AI模型加载慢：首次运行需下载模型，请耐心等待
4. 界面无法访问：检查防火墙设置

📞 技术信息:
- 版本: 1.0.0
- 端口: 8000
- 支持格式: PNG, JPG, JPEG, BMP
- API文档: http://127.0.0.1:8000/docs
"""
        
        with open(exe_dir / "使用说明.txt", "w", encoding="utf-8") as f:
            f.write(readme_content)
        
        print(f"📦 便携版已创建: {exe_dir}")
        print("\n🎉 打包完成! 可以分发exe文件了!")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ 打包失败: {e}")
        print(f"错误输出: {e.stderr}")
        return False
    except Exception as e:
        print(f"❌ 打包过程中出现错误: {e}")
        return False
    
    return True

def install_pyinstaller():
    """安装PyInstaller"""
    try:
        import PyInstaller
        print("✅ PyInstaller已安装")
        return True
    except ImportError:
        print("📥 正在安装PyInstaller...")
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
            print("✅ PyInstaller安装成功")
            return True
        except subprocess.CalledProcessError:
            print("❌ PyInstaller安装失败")
            return False

if __name__ == "__main__":
    print("🚀 TianMu智能服务器打包工具")
    print("=" * 40)
    
    # 检查并安装PyInstaller
    if not install_pyinstaller():
        input("按回车键退出...")
        sys.exit(1)
    
    # 开始打包
    success = build_exe()
    
    if success:
        print("\n✨ 打包完成!")
        print("可以将dist目录下的文件分发给其他用户使用")
    else:
        print("\n💥 打包失败，请检查错误信息")
    
    input("按回车键退出...")