# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['run_server.py'],
    pathex=['.'],
    binaries=[],
    datas=[('app', 'app'), ('Data', 'Data')],
    hiddenimports=['uvicorn', 'uvicorn.lifespan', 'uvicorn.lifespan.on', 'uvicorn.protocols', 'uvicorn.protocols.websockets', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets.auto', 'uvicorn.loops', 'uvicorn.loops.auto', 'paddleocr', 'paddlepaddle', 'face_recognition', 'cv2', 'pyodbc', 'sqlite3'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TianMu智能服务器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
