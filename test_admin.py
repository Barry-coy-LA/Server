# test_admin.py - 用于测试管理后台功能
from fastapi import FastAPI, Request, HTTPException, Depends, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import hashlib
import jwt
from datetime import datetime, timedelta
from typing import Optional
import psutil
import platform

app = FastAPI(title="TianMu管理后台测试")

# 简化的认证配置
SECRET_KEY = "tianmu_test_secret"
ALGORITHM = "HS256"
ADMIN_PASSWORD = "tianmu2025"

security = HTTPBearer(auto_error=False)

class LoginRequest(BaseModel):
    password: str

def verify_password(password: str) -> bool:
    return password == ADMIN_PASSWORD

def create_access_token(data: dict):
    expire = datetime.utcnow() + timedelta(hours=8)
    to_encode = data.copy()
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if credentials is None:
        raise HTTPException(status_code=401, detail="需要认证")
    
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username != "admin":
            raise HTTPException(status_code=401, detail="无效用户")
        return username
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token已过期")
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="无效Token")

# 登录页面
@app.get("/admin/login", response_class=HTMLResponse)
async def login_page():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>管理员登录</title>
    <style>
        body { font-family: Arial, sans-serif; background: #f5f5f5; }
        .login-box { 
            max-width: 400px; margin: 100px auto; padding: 40px; 
            background: white; border-radius: 10px; box-shadow: 0 4px 20px rgba(0,0,0,0.1);
        }
        input { width: 100%; padding: 12px; margin: 10px 0; border: 1px solid #ddd; border-radius: 5px; }
        button { width: 100%; padding: 12px; background: #007bff; color: white; border: none; border-radius: 5px; cursor: pointer; }
        button:hover { background: #0056b3; }
        .error { color: red; margin: 10px 0; }
    </style>
</head>
<body>
    <div class="login-box">
        <h2>TianMu管理后台</h2>
        <div id="error" class="error"></div>
        <form id="loginForm">
            <input type="password" id="password" placeholder="管理员密码" required>
            <button type="submit">登录</button>
        </form>
    </div>
    
    <script>
        document.getElementById('loginForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const password = document.getElementById('password').value;
            
            try {
                const response = await fetch('/admin/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password })
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    localStorage.setItem('admin_token', data.access_token);
                    window.location.href = '/admin/dashboard';
                } else {
                    document.getElementById('error').textContent = data.detail;
                }
            } catch (error) {
                document.getElementById('error').textContent = '登录失败：' + error.message;
            }
        });
    </script>
</body>
</html>
    """

# 登录API
@app.post("/admin/api/login")
async def login(request: LoginRequest):
    if not verify_password(request.password):
        raise HTTPException(status_code=401, detail="密码错误")
    
    token = create_access_token(data={"sub": "admin"})
    return {"access_token": token, "token_type": "bearer"}

# 仪表板页面
@app.get("/admin/dashboard", response_class=HTMLResponse)
async def dashboard():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>管理仪表板</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; background: #f5f5f5; }
        .header { background: #007bff; color: white; padding: 1rem 2rem; display: flex; justify-content: space-between; }
        .container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
        .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem; margin-bottom: 2rem; }
        .card { background: white; padding: 1.5rem; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .stat-number { font-size: 2rem; font-weight: bold; color: #007bff; }
        .logout-btn { background: rgba(255,255,255,0.2); color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer; }
        .system-info { background: white; padding: 1.5rem; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        .info-item { margin: 0.5rem 0; padding: 0.5rem; background: #f8f9fa; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>TianMu管理后台</h1>
        <button class="logout-btn" onclick="logout()">退出登录</button>
    </div>
    
    <div class="container">
        <div class="stats">
            <div class="card">
                <div class="stat-number" id="totalRequests">-</div>
                <div>总请求数</div>
            </div>
            <div class="card">
                <div class="stat-number" id="successRate">-</div>
                <div>成功率</div>
            </div>
            <div class="card">
                <div class="stat-number" id="avgTime">-</div>
                <div>平均响应时间</div>
            </div>
        </div>
        
        <div class="system-info">
            <h3>系统信息</h3>
            <div id="systemInfo">正在加载...</div>
        </div>
    </div>
    
    <script>
        const token = localStorage.getItem('admin_token');
        if (!token) {
            window.location.href = '/admin/login';
        }
        
        async function apiCall(url) {
            const response = await fetch(url, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            
            if (response.status === 401) {
                localStorage.removeItem('admin_token');
                window.location.href = '/admin/login';
                return null;
            }
            
            return response.ok ? await response.json() : null;
        }
        
        async function loadStats() {
            const stats = await apiCall('/admin/api/stats');
            if (stats) {
                document.getElementById('totalRequests').textContent = stats.total_requests || 0;
                document.getElementById('successRate').textContent = (stats.success_rate || 100) + '%';
                document.getElementById('avgTime').textContent = (stats.avg_time || 0) + 'ms';
            }
        }
        
        async function loadSystemInfo() {
            const info = await apiCall('/admin/api/system');
            if (info) {
                const html = `
                    <div class="info-item">操作系统: ${info.platform} ${info.release}</div>
                    <div class="info-item">CPU使用率: ${info.cpu_percent}%</div>
                    <div class="info-item">内存使用率: ${info.memory_percent}%</div>
                    <div class="info-item">磁盘使用率: ${info.disk_percent}%</div>
                `;
                document.getElementById('systemInfo').innerHTML = html;
            }
        }
        
        function logout() {
            localStorage.removeItem('admin_token');
            window.location.href = '/admin/login';
        }
        
        // 加载数据
        loadStats();
        loadSystemInfo();
        
        // 每30秒刷新一次
        setInterval(() => {
            loadStats();
            loadSystemInfo();
        }, 30000);
    </script>
</body>
</html>
    """

# 统计API
@app.get("/admin/api/stats")
async def get_stats(current_user: str = Depends(get_current_user)):
    # 这里返回模拟数据，实际使用时连接到usage_tracker
    return {
        "total_requests": 150,
        "success_rate": 95.5,
        "avg_time": 1250
    }

# 系统信息API
@app.get("/admin/api/system")
async def get_system_info(current_user: str = Depends(get_current_user)):
    return {
        "platform": platform.system(),
        "release": platform.release(),
        "cpu_percent": psutil.cpu_percent(interval=1),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage('/').percent
    }

@app.get("/")
async def root():
    return {"message": "TianMu管理后台测试", "admin_login": "/admin/login"}

if __name__ == "__main__":
    import uvicorn
    print("🚀 启动TianMu管理后台测试服务器...")
    print("📝 访问地址: http://127.0.0.1:8000/admin/login")
    print("🔑 默认密码: tianmu2025")
    uvicorn.run(app, host="127.0.0.1", port=8000)