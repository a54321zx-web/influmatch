"""
auth.py — JWT 인증 + bcrypt 비밀번호 암호화
"""

import os
import bcrypt
from datetime import datetime, timedelta
from jose import JWTError, jwt

SECRET_KEY = os.environ.get("JWT_SECRET", "influmatch-secret-key-change-in-production")
ALGORITHM  = "HS256"
EXPIRE_DAYS = 7


# ── 비밀번호 ──────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except:
        return False


# ── JWT 토큰 ──────────────────────────────────────────────────
def create_token(data: dict) -> str:
    payload = {
        **data,
        "exp": datetime.utcnow() + timedelta(days=EXPIRE_DAYS)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ── FastAPI 의존성 ─────────────────────────────────────────────
from fastapi import Request, HTTPException

def get_current_user(request: Request) -> dict:
    """
    Authorization: Bearer <token> 헤더에서 유저 정보 추출
    인증 실패 시 401 반환
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    token = auth.split(" ", 1)[1]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="토큰이 만료되었거나 유효하지 않습니다")
    return payload

def get_current_user_optional(request: Request) -> dict | None:
    """인증 선택적 — 없어도 None 반환"""
    try:
        return get_current_user(request)
    except:
        return None