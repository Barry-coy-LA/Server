# app/middleware/auth.py
from fastapi import HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional
import hashlib
import os

# JWT配置
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "tianmu_secret_key_change_in_production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480  # 8小时

# 管理员密码配置
ADMIN_PASSWORD_HASH = hashlib.sha256("tianmu2025".encode()).hexdigest()  # 默认密码: tianmu2025

security = HTTPBearer(auto_error=False)

def verify_password(password: str) -> bool:
    """验证管理员密码"""
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    return password_hash == ADMIN_PASSWORD_HASH

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """创建JWT访问令牌"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def verify_token(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    """验证JWT令牌"""
    if credentials is None:
        raise HTTPException(status_code=401, detail="需要认证令牌")
    
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None or username != "admin":
            raise HTTPException(status_code=401, detail="无效的认证令牌")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="无效的认证令牌")

def admin_required(current_user: str = Depends(verify_token)):
    """管理员权限装饰器"""
    return current_user