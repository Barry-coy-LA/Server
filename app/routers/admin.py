# app/routers/admin.py - 清晰的后台管理路由
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
import jwt
from datetime import datetime, timedelta
import hashlib
import psutil
import platform

# ========== 配置区域 ==========
SECRET_KEY = "tianmu_secret_key_2025"
ALGORITHM = "HS256"
ADMIN_PASSWORD = "tianmu2025"
TOKEN_EXPIRE_HOURS = 8

# ========== 数据模型 ==========
class LoginRequest(BaseModel):
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = TOKEN_EXPIRE_HOURS * 3600

class StatsResponse(BaseModel):
    total_requests: int
    success_requests: int
    failed_requests: int
    success_rate: float
    avg_processing_time: float
    total_file_size: int

class SystemInfoResponse(BaseModel):
    platform: str
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    uptime: str

# ========== 认证工具函数 ==========
security = HTTPBearer(auto_error=False)

def verify_password(password: str) -> bool:
    """验证管理员密码"""
    return password == ADMIN_PASSWORD

def create_access_token(username: str) -> str:
    """创建JWT访问令牌"""
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": username,
        "exp": expire,
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> str:
    """验证JWT令牌并返回用户名"""
    if not credentials:
        raise HTTPException(status_code=401, detail="需要认证令牌")
    
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username != "admin":
            raise HTTPException(status_code=401, detail="无效用户")
        return username
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="令牌已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效令牌")

# app/routers/admin.py - 连接真实数据的后台管理路由
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional
import jwt
from datetime import datetime, timedelta
import hashlib
import psutil
import platform

# 导入真实的使用追踪系统
from app.services.usage_tracker import usage_tracker, ServiceType

# ========== 配置区域 ==========
SECRET_KEY = "tianmu_secret_key_2025"
ALGORITHM = "HS256"
ADMIN_PASSWORD = "tianmu2025"
TOKEN_EXPIRE_HOURS = 8

# ========== 数据模型 ==========
class LoginRequest(BaseModel):
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = TOKEN_EXPIRE_HOURS * 3600

class StatsResponse(BaseModel):
    total_requests: int
    success_requests: int
    failed_requests: int
    success_rate: float
    avg_processing_time: float
    total_file_size: int

class SystemInfoResponse(BaseModel):
    platform: str
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    uptime: str

# ========== 认证工具函数 ==========
security = HTTPBearer(auto_error=False)

def verify_password(password: str) -> bool:
    """验证管理员密码"""
    return password == ADMIN_PASSWORD

def create_access_token(username: str) -> str:
    """创建JWT访问令牌"""
    expire = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    payload = {
        "sub": username,
        "exp": expire,
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> str:
    """验证JWT令牌并返回用户名"""
    if not credentials:
        raise HTTPException(status_code=401, detail="需要认证令牌")
    
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        if username != "admin":
            raise HTTPException(status_code=401, detail="无效用户")
        return username
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="令牌已过期")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效令牌")

# ========== 业务逻辑函数 ==========
async def get_real_statistics() -> StatsResponse:
    """获取真实统计数据"""
    try:
        # 获取24小时内的统计数据
        stats = await usage_tracker.get_statistics(hours=24)
        
        # 计算成功率
        total = stats.get("total_requests", 0)
        success = stats.get("success_requests", 0)
        success_rate = (success / total * 100) if total > 0 else 100.0
        
        return StatsResponse(
            total_requests=total,
            success_requests=success,
            failed_requests=stats.get("failed_requests", 0),
            success_rate=round(success_rate, 1),
            avg_processing_time=stats.get("avg_processing_time", 0.0),
            total_file_size=stats.get("total_file_size", 0)
        )
    except Exception as e:
        # 如果获取数据失败，返回默认值
        print(f"获取统计数据失败: {e}")
        return StatsResponse(
            total_requests=0,
            success_requests=0,
            failed_requests=0,
            success_rate=100.0,
            avg_processing_time=0.0,
            total_file_size=0
        )

async def get_usage_records_summary():
    """获取使用记录摘要"""
    try:
        # 获取最近100条记录
        recent_records = await usage_tracker.get_records(limit=100)
        
        # 按服务类型分组统计
        service_stats = {}
        for record in recent_records:
            service_type = record.service_type.value
            if service_type not in service_stats:
                service_stats[service_type] = {
                    "count": 0,
                    "success": 0,
                    "avg_time": 0.0,
                    "total_time": 0.0
                }
            
            service_stats[service_type]["count"] += 1
            if record.success:
                service_stats[service_type]["success"] += 1
            service_stats[service_type]["total_time"] += record.processing_time
        
        # 计算平均时间
        for service in service_stats.values():
            if service["count"] > 0:
                service["avg_time"] = service["total_time"] / service["count"]
        
        return service_stats
    except Exception as e:
        print(f"获取使用记录摘要失败: {e}")
        return {}

def get_system_info() -> SystemInfoResponse:
    """获取系统信息"""
    return SystemInfoResponse(
        platform=f"{platform.system()} {platform.release()}",
        cpu_percent=round(psutil.cpu_percent(interval=1), 1),
        memory_percent=round(psutil.virtual_memory().percent, 1),
        disk_percent=round(psutil.disk_usage('/').percent, 1),
        uptime="获取中..."  # 可以后续添加实际计算
    )

def format_file_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    import math
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_names[i]}"

# ========== 路由器初始化 ==========
router = APIRouter(prefix="/admin", tags=["管理后台"])

# ========== 页面路由 ==========
@router.get("/login", response_class=HTMLResponse, summary="管理员登录页面")
async def login_page():
    """管理员登录页面"""
    return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TianMu管理后台 - 登录</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .login-container {
            background: white;
            border-radius: 16px;
            padding: 48px 40px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
            width: 100%;
            max-width: 400px;
            text-align: center;
        }
        .logo { font-size: 3rem; margin-bottom: 16px; }
        .title { font-size: 24px; font-weight: 600; color: #333; margin-bottom: 32px; }
        .form-group { margin-bottom: 20px; text-align: left; }
        .form-label { display: block; margin-bottom: 8px; font-weight: 500; color: #555; }
        .form-input {
            width: 100%;
            padding: 14px 16px;
            border: 2px solid #e1e5e9;
            border-radius: 8px;
            font-size: 16px;
            transition: border-color 0.3s ease;
        }
        .form-input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        .login-btn {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s ease;
        }
        .login-btn:hover { transform: translateY(-1px); }
        .login-btn:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
        .error-message {
            background: #fee;
            color: #c53030;
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 16px;
            border-left: 4px solid #e53e3e;
            text-align: left;
            display: none;
        }
        .back-link {
            display: inline-block;
            margin-top: 24px;
            color: #667eea;
            text-decoration: none;
            font-size: 14px;
        }
        .back-link:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="logo">🔐</div>
        <h1 class="title">管理后台登录</h1>
        
        <div id="errorMessage" class="error-message"></div>
        
        <form id="loginForm">
            <div class="form-group">
                <label class="form-label" for="password">管理员密码</label>
                <input 
                    type="password" 
                    id="password" 
                    class="form-input" 
                    placeholder="请输入管理员密码"
                    required
                    autofocus
                >
            </div>
            
            <button type="submit" class="login-btn" id="loginBtn">
                登录管理后台
            </button>
        </form>
        
        <a href="/" class="back-link">← 返回首页</a>
    </div>

    <script>
        const loginForm = document.getElementById('loginForm');
        const passwordInput = document.getElementById('password');
        const loginBtn = document.getElementById('loginBtn');
        const errorMessage = document.getElementById('errorMessage');

        // 检查是否已登录
        if (localStorage.getItem('admin_token')) {
            window.location.href = '/admin/dashboard';
        }

        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const password = passwordInput.value.trim();
            if (!password) {
                showError('请输入密码');
                return;
            }

            setLoading(true);
            hideError();

            try {
                const response = await fetch('/admin/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password })
                });

                const data = await response.json();

                if (response.ok) {
                    localStorage.setItem('admin_token', data.access_token);
                    localStorage.setItem('admin_expires', Date.now() + (data.expires_in * 1000));
                    window.location.href = '/admin/dashboard';
                } else {
                    showError(data.detail || '登录失败');
                }
            } catch (error) {
                showError('网络连接失败，请重试');
            } finally {
                setLoading(false);
            }
        });

        function showError(message) {
            errorMessage.textContent = message;
            errorMessage.style.display = 'block';
        }

        function hideError() {
            errorMessage.style.display = 'none';
        }

        function setLoading(loading) {
            loginBtn.disabled = loading;
            loginBtn.textContent = loading ? '登录中...' : '登录管理后台';
        }
    </script>
</body>
</html>
    """

@router.get("/dashboard", response_class=HTMLResponse, summary="管理仪表板页面")
async def dashboard_page():
    """管理仪表板页面"""
    return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TianMu管理后台 - 仪表板</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #f8fafc;
            color: #334155;
            line-height: 1.6;
        }
        
        /* 顶部导航栏 */
        .navbar {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
        }
        .navbar-brand { font-size: 1.25rem; font-weight: 600; }
        .navbar-user {
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        .logout-btn {
            background: rgba(255, 255, 255, 0.2);
            color: white;
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            cursor: pointer;
            transition: background 0.3s ease;
        }
        .logout-btn:hover { background: rgba(255, 255, 255, 0.3); }
        
        /* 主容器 */
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }
        
        /* 统计卡片网格 */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        
        /* 卡片样式 */
        .card {
            background: white;
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
            border: 1px solid #e2e8f0;
            transition: all 0.3s ease;
        }
        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.12);
        }
        
        /* 统计卡片 */
        .stat-card {
            text-align: center;
        }
        .stat-icon {
            font-size: 2.5rem;
            margin-bottom: 1rem;
            display: block;
        }
        .stat-number {
            font-size: 2.5rem;
            font-weight: 700;
            color: #667eea;
            margin-bottom: 0.5rem;
        }
        .stat-label {
            color: #64748b;
            font-size: 0.875rem;
            font-weight: 500;
        }
        
        /* 服务统计表格 */
        .service-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }
        .service-table th,
        .service-table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #e2e8f0;
        }
        .service-table th {
            background: #f1f5f9;
            font-weight: 600;
        }
        
        /* 系统信息网格 */
        .system-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-top: 1rem;
        }
        .info-item {
            background: #f1f5f9;
            padding: 1rem;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }
        .info-label {
            font-size: 0.875rem;
            color: #64748b;
            margin-bottom: 0.25rem;
        }
        .info-value {
            font-size: 1.125rem;
            font-weight: 600;
            color: #1e293b;
        }
        
        /* 加载状态 */
        .loading {
            text-align: center;
            padding: 2rem;
            color: #64748b;
            font-style: italic;
        }
        
        /* 响应式设计 */
        @media (max-width: 768px) {
            .navbar {
                flex-direction: column;
                gap: 1rem;
                text-align: center;
            }
            .container { padding: 1rem; }
            .stats-grid { grid-template-columns: 1fr; }
        }

        /* 刷新指示器 */
        .refresh-indicator {
            position: fixed;
            top: 80px;
            right: 20px;
            background: #667eea;
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 12px;
            opacity: 0;
            transition: opacity 0.3s ease;
        }
        .refresh-indicator.show {
            opacity: 1;
        }
    </style>
</head>
<body>
    <!-- 刷新指示器 -->
    <div id="refreshIndicator" class="refresh-indicator">数据更新中...</div>

    <!-- 顶部导航栏 -->
    <nav class="navbar">
        <div class="navbar-brand">🚀 TianMu智能服务器管理后台</div>
        <div class="navbar-user">
            <span>👤 管理员</span>
            <button class="logout-btn" onclick="logout()">退出登录</button>
        </div>
    </nav>

    <!-- 主内容区域 -->
    <div class="container">
        <!-- 统计卡片 -->
        <div class="stats-grid">
            <div class="card stat-card">
                <span class="stat-icon">📊</span>
                <div class="stat-number" id="totalRequests">-</div>
                <div class="stat-label">总请求数（24小时）</div>
            </div>
            
            <div class="card stat-card">
                <span class="stat-icon">✅</span>
                <div class="stat-number" id="successRate">-</div>
                <div class="stat-label">成功率</div>
            </div>
            
            <div class="card stat-card">
                <span class="stat-icon">⚡</span>
                <div class="stat-number" id="avgTime">-</div>
                <div class="stat-label">平均响应时间</div>
            </div>
            
            <div class="card stat-card">
                <span class="stat-icon">💾</span>
                <div class="stat-number" id="totalSize">-</div>
                <div class="stat-label">数据处理量（24小时）</div>
            </div>
        </div>

        <!-- 服务使用统计 -->
        <div class="card">
            <h3 style="margin-bottom: 1rem; color: #1e293b;">📈 服务使用统计</h3>
            <div id="serviceStats" class="loading">正在加载服务统计...</div>
        </div>

        <!-- 系统信息卡片 -->
        <div class="card" style="margin-top: 1.5rem;">
            <h3 style="margin-bottom: 1rem; color: #1e293b;">🖥️ 系统监控</h3>
            <div id="systemInfo" class="loading">正在加载系统信息...</div>
        </div>
    </div>

    <script>
        // 全局变量
        const token = localStorage.getItem('admin_token');
        const expires = localStorage.getItem('admin_expires');

        // 检查认证状态
        if (!token || !expires || Date.now() >= parseInt(expires)) {
            localStorage.removeItem('admin_token');
            localStorage.removeItem('admin_expires');
            window.location.href = '/admin/login';
        }

        // API调用工具函数
        async function apiCall(endpoint) {
            try {
                const response = await fetch(`/admin/api${endpoint}`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                });

                if (response.status === 401) {
                    logout();
                    return null;
                }

                return response.ok ? await response.json() : null;
            } catch (error) {
                console.error('API调用失败:', error);
                return null;
            }
        }

        // 显示刷新指示器
        function showRefreshIndicator() {
            const indicator = document.getElementById('refreshIndicator');
            indicator.classList.add('show');
            setTimeout(() => {
                indicator.classList.remove('show');
            }, 1000);
        }

        // 加载统计数据
        async function loadStatistics() {
            showRefreshIndicator();
            const stats = await apiCall('/statistics');
            if (stats) {
                document.getElementById('totalRequests').textContent = stats.total_requests.toLocaleString();
                document.getElementById('successRate').textContent = stats.success_rate.toFixed(1) + '%';
                document.getElementById('avgTime').textContent = (stats.avg_processing_time * 1000).toFixed(0) + 'ms';
                document.getElementById('totalSize').textContent = formatFileSize(stats.total_file_size);
            }
        }

        // 加载服务统计
        async function loadServiceStats() {
            const serviceStats = await apiCall('/service-stats');
            if (serviceStats && Object.keys(serviceStats).length > 0) {
                let tableHtml = `
                    <table class="service-table">
                        <thead>
                            <tr>
                                <th>服务类型</th>
                                <th>请求次数</th>
                                <th>成功次数</th>
                                <th>成功率</th>
                                <th>平均响应时间</th>
                            </tr>
                        </thead>
                        <tbody>
                `;
                
                for (const [service, stats] of Object.entries(serviceStats)) {
                    const successRate = stats.count > 0 ? (stats.success / stats.count * 100).toFixed(1) : '100';
                    const serviceName = getServiceName(service);
                    
                    tableHtml += `
                        <tr>
                            <td>${serviceName}</td>
                            <td>${stats.count}</td>
                            <td>${stats.success}</td>
                            <td>${successRate}%</td>
                            <td>${(stats.avg_time * 1000).toFixed(0)}ms</td>
                        </tr>
                    `;
                }
                
                tableHtml += '</tbody></table>';
                document.getElementById('serviceStats').innerHTML = tableHtml;
            } else {
                document.getElementById('serviceStats').innerHTML = '<p style="text-align: center; color: #64748b;">暂无服务使用记录</p>';
            }
        }

        // 加载系统信息
        async function loadSystemInfo() {
            const system = await apiCall('/system-info');
            if (system) {
                document.getElementById('systemInfo').innerHTML = `
                    <div class="system-grid">
                        <div class="info-item">
                            <div class="info-label">操作系统</div>
                            <div class="info-value">${system.platform}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">CPU使用率</div>
                            <div class="info-value">${system.cpu_percent}%</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">内存使用率</div>
                            <div class="info-value">${system.memory_percent}%</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">磁盘使用率</div>
                            <div class="info-value">${system.disk_percent}%</div>
                        </div>
                    </div>
                `;
            }
        }

        // 工具函数
        function formatFileSize(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }

        function getServiceName(service) {
            const names = {
                'ocr': 'OCR识别',
                'face_recognition': '人脸识别',
                'face_register': '人脸注册',
                'face_verify': '人脸验证',
                'face_detect': '人脸检测'
            };
            return names[service] || service;
        }

        function logout() {
            localStorage.removeItem('admin_token');
            localStorage.removeItem('admin_expires');
            window.location.href = '/admin/login';
        }

        // 初始化加载
        loadStatistics();
        loadServiceStats();
        loadSystemInfo();

        // 定时刷新（每30秒）
        setInterval(() => {
            loadStatistics();
            loadServiceStats();
            loadSystemInfo();
        }, 30000);
    </script>
</body>
</html>
    """

# ========== API路由 ==========
@router.post("/api/login", response_model=LoginResponse, summary="管理员登录")
async def login_api(request: LoginRequest):
    """管理员登录API"""
    if not verify_password(request.password):
        raise HTTPException(status_code=401, detail="密码错误")
    
    access_token = create_access_token("admin")
    return LoginResponse(access_token=access_token)

@router.get("/api/statistics", response_model=StatsResponse, summary="获取统计数据")
async def get_statistics(current_user: str = Depends(verify_token)):
    """获取真实使用统计数据"""
    return await get_real_statistics()

@router.get("/api/service-stats", summary="获取服务统计数据")
async def get_service_stats(current_user: str = Depends(verify_token)):
    """获取各服务的使用统计"""
    return await get_usage_records_summary()

@router.get("/api/system-info", response_model=SystemInfoResponse, summary="获取系统信息") 
async def get_system_info_api(current_user: str = Depends(verify_token)):
    """获取系统监控信息"""
    return get_system_info()

@router.get("/api/health", summary="健康检查")
async def health_check(current_user: str = Depends(verify_token)):
    """管理后台健康检查"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "user": current_user
    }

def get_system_info() -> SystemInfoResponse:
    """获取系统信息"""
    return SystemInfoResponse(
        platform=f"{platform.system()} {platform.release()}",
        cpu_percent=round(psutil.cpu_percent(interval=1), 1),
        memory_percent=round(psutil.virtual_memory().percent, 1),
        disk_percent=round(psutil.disk_usage('/').percent, 1),
        uptime="获取中..."  # 可以后续添加实际计算
    )

def format_file_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    import math
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_names[i]}"

# ========== 路由器初始化 ==========
router = APIRouter(prefix="/admin", tags=["管理后台"])

# ========== 页面路由 ==========
@router.get("/login", response_class=HTMLResponse, summary="管理员登录页面")
async def login_page():
    """管理员登录页面"""
    return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TianMu管理后台 - 登录</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }
        .login-container {
            background: white;
            border-radius: 16px;
            padding: 48px 40px;
            box-shadow: 0 20px 40px rgba(0, 0, 0, 0.1);
            width: 100%;
            max-width: 400px;
            text-align: center;
        }
        .logo { font-size: 3rem; margin-bottom: 16px; }
        .title { font-size: 24px; font-weight: 600; color: #333; margin-bottom: 32px; }
        .form-group { margin-bottom: 20px; text-align: left; }
        .form-label { display: block; margin-bottom: 8px; font-weight: 500; color: #555; }
        .form-input {
            width: 100%;
            padding: 14px 16px;
            border: 2px solid #e1e5e9;
            border-radius: 8px;
            font-size: 16px;
            transition: border-color 0.3s ease;
        }
        .form-input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        .login-btn {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s ease;
        }
        .login-btn:hover { transform: translateY(-1px); }
        .login-btn:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
        .error-message {
            background: #fee;
            color: #c53030;
            padding: 12px;
            border-radius: 6px;
            margin-bottom: 16px;
            border-left: 4px solid #e53e3e;
            text-align: left;
            display: none;
        }
        .back-link {
            display: inline-block;
            margin-top: 24px;
            color: #667eea;
            text-decoration: none;
            font-size: 14px;
        }
        .back-link:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="logo">🔐</div>
        <h1 class="title">管理后台登录</h1>
        
        <div id="errorMessage" class="error-message"></div>
        
        <form id="loginForm">
            <div class="form-group">
                <label class="form-label" for="password">管理员密码</label>
                <input 
                    type="password" 
                    id="password" 
                    class="form-input" 
                    placeholder="请输入管理员密码"
                    required
                    autofocus
                >
            </div>
            
            <button type="submit" class="login-btn" id="loginBtn">
                登录管理后台
            </button>
        </form>
        
        <a href="/" class="back-link">← 返回首页</a>
    </div>

    <script>
        const loginForm = document.getElementById('loginForm');
        const passwordInput = document.getElementById('password');
        const loginBtn = document.getElementById('loginBtn');
        const errorMessage = document.getElementById('errorMessage');

        // 检查是否已登录
        if (localStorage.getItem('admin_token')) {
            window.location.href = '/admin/dashboard';
        }

        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const password = passwordInput.value.trim();
            if (!password) {
                showError('请输入密码');
                return;
            }

            setLoading(true);
            hideError();

            try {
                const response = await fetch('/admin/api/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password })
                });

                const data = await response.json();

                if (response.ok) {
                    localStorage.setItem('admin_token', data.access_token);
                    localStorage.setItem('admin_expires', Date.now() + (data.expires_in * 1000));
                    window.location.href = '/admin/dashboard';
                } else {
                    showError(data.detail || '登录失败');
                }
            } catch (error) {
                showError('网络连接失败，请重试');
            } finally {
                setLoading(false);
            }
        });

        function showError(message) {
            errorMessage.textContent = message;
            errorMessage.style.display = 'block';
        }

        function hideError() {
            errorMessage.style.display = 'none';
        }

        function setLoading(loading) {
            loginBtn.disabled = loading;
            loginBtn.textContent = loading ? '登录中...' : '登录管理后台';
        }
    </script>
</body>
</html>
    """

@router.get("/dashboard", response_class=HTMLResponse, summary="管理仪表板页面")
async def dashboard_page():
    """管理仪表板页面"""
    return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TianMu管理后台 - 仪表板</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #f8fafc;
            color: #334155;
            line-height: 1.6;
        }
        
        /* 顶部导航栏 */
        .navbar {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
        }
        .navbar-brand { font-size: 1.25rem; font-weight: 600; }
        .navbar-user {
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        .logout-btn {
            background: rgba(255, 255, 255, 0.2);
            color: white;
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 6px;
            cursor: pointer;
            transition: background 0.3s ease;
        }
        .logout-btn:hover { background: rgba(255, 255, 255, 0.3); }
        
        /* 主容器 */
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
        }
        
        /* 统计卡片网格 */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        
        /* 卡片样式 */
        .card {
            background: white;
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);
            border: 1px solid #e2e8f0;
            transition: all 0.3s ease;
        }
        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.12);
        }
        
        /* 统计卡片 */
        .stat-card {
            text-align: center;
        }
        .stat-icon {
            font-size: 2.5rem;
            margin-bottom: 1rem;
            display: block;
        }
        .stat-number {
            font-size: 2.5rem;
            font-weight: 700;
            color: #667eea;
            margin-bottom: 0.5rem;
        }
        .stat-label {
            color: #64748b;
            font-size: 0.875rem;
            font-weight: 500;
        }
        
        /* 系统信息网格 */
        .system-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-top: 1rem;
        }
        .info-item {
            background: #f1f5f9;
            padding: 1rem;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }
        .info-label {
            font-size: 0.875rem;
            color: #64748b;
            margin-bottom: 0.25rem;
        }
        .info-value {
            font-size: 1.125rem;
            font-weight: 600;
            color: #1e293b;
        }
        
        /* 加载状态 */
        .loading {
            text-align: center;
            padding: 2rem;
            color: #64748b;
            font-style: italic;
        }
        
        /* 响应式设计 */
        @media (max-width: 768px) {
            .navbar {
                flex-direction: column;
                gap: 1rem;
                text-align: center;
            }
            .container { padding: 1rem; }
            .stats-grid { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <!-- 顶部导航栏 -->
    <nav class="navbar">
        <div class="navbar-brand">🚀 TianMu智能服务器管理后台</div>
        <div class="navbar-user">
            <span>👤 管理员</span>
            <button class="logout-btn" onclick="logout()">退出登录</button>
        </div>
    </nav>

    <!-- 主内容区域 -->
    <div class="container">
        <!-- 统计卡片 -->
        <div class="stats-grid">
            <div class="card stat-card">
                <span class="stat-icon">📊</span>
                <div class="stat-number" id="totalRequests">-</div>
                <div class="stat-label">总请求数</div>
            </div>
            
            <div class="card stat-card">
                <span class="stat-icon">✅</span>
                <div class="stat-number" id="successRate">-</div>
                <div class="stat-label">成功率</div>
            </div>
            
            <div class="card stat-card">
                <span class="stat-icon">⚡</span>
                <div class="stat-number" id="avgTime">-</div>
                <div class="stat-label">平均响应时间</div>
            </div>
            
            <div class="card stat-card">
                <span class="stat-icon">💾</span>
                <div class="stat-number" id="totalSize">-</div>
                <div class="stat-label">数据处理量</div>
            </div>
        </div>

        <!-- 系统信息卡片 -->
        <div class="card">
            <h3 style="margin-bottom: 1rem; color: #1e293b;">🖥️ 系统监控</h3>
            <div id="systemInfo" class="loading">正在加载系统信息...</div>
        </div>
    </div>

    <script>
        // 全局变量
        const token = localStorage.getItem('admin_token');
        const expires = localStorage.getItem('admin_expires');

        // 检查认证状态
        if (!token || !expires || Date.now() >= parseInt(expires)) {
            localStorage.removeItem('admin_token');
            localStorage.removeItem('admin_expires');
            window.location.href = '/admin/login';
        }

        // API调用工具函数
        async function apiCall(endpoint) {
            try {
                const response = await fetch(`/admin/api${endpoint}`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                });

                if (response.status === 401) {
                    logout();
                    return null;
                }

                return response.ok ? await response.json() : null;
            } catch (error) {
                console.error('API调用失败:', error);
                return null;
            }
        }

        // 加载统计数据
        async function loadStatistics() {
            const stats = await apiCall('/statistics');
            if (stats) {
                document.getElementById('totalRequests').textContent = stats.total_requests.toLocaleString();
                document.getElementById('successRate').textContent = stats.success_rate.toFixed(1) + '%';
                document.getElementById('avgTime').textContent = (stats.avg_processing_time * 1000).toFixed(0) + 'ms';
                document.getElementById('totalSize').textContent = formatFileSize(stats.total_file_size);
            }
        }

        // 加载系统信息
        async function loadSystemInfo() {
            const system = await apiCall('/system-info');
            if (system) {
                document.getElementById('systemInfo').innerHTML = `
                    <div class="system-grid">
                        <div class="info-item">
                            <div class="info-label">操作系统</div>
                            <div class="info-value">${system.platform}</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">CPU使用率</div>
                            <div class="info-value">${system.cpu_percent}%</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">内存使用率</div>
                            <div class="info-value">${system.memory_percent}%</div>
                        </div>
                        <div class="info-item">
                            <div class="info-label">磁盘使用率</div>
                            <div class="info-value">${system.disk_percent}%</div>
                        </div>
                    </div>
                `;
            }
        }

        // 工具函数
        function formatFileSize(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }

        function logout() {
            localStorage.removeItem('admin_token');
            localStorage.removeItem('admin_expires');
            window.location.href = '/admin/login';
        }

        // 初始化加载
        loadStatistics();
        loadSystemInfo();

        // 定时刷新（每30秒）
        setInterval(() => {
            loadStatistics();
            loadSystemInfo();
        }, 30000);
    </script>
</body>
</html>
    """

# ========== API路由 ==========
@router.post("/api/login", response_model=LoginResponse, summary="管理员登录")
async def login_api(request: LoginRequest):
    """管理员登录API"""
    if not verify_password(request.password):
        raise HTTPException(status_code=401, detail="密码错误")
    
    access_token = create_access_token("admin")
    return LoginResponse(access_token=access_token)

@router.get("/api/statistics", response_model=StatsResponse, summary="获取统计数据")
async def get_statistics(current_user: str = Depends(verify_token)):
    """获取真实使用统计数据"""
    return await get_real_statistics()

@router.get("/api/system-info", response_model=SystemInfoResponse, summary="获取系统信息") 
async def get_system_info_api(current_user: str = Depends(verify_token)):
    """获取系统监控信息"""
    return get_system_info()

@router.get("/api/health", summary="健康检查")
async def health_check(current_user: str = Depends(verify_token)):
    """管理后台健康检查"""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "user": current_user
    }