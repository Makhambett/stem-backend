from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database import get_db
from models import User
from pydantic import BaseModel
from typing import Optional
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta

router = APIRouter()

SECRET_KEY = "stem-academia-2026"
ALGORITHM = "HS256"
EXPIRE_DAYS = 7

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")

# --- Pydantic схемы ---
class RegisterData(BaseModel):
    name: str
    email: str
    password: str
    phone: Optional[str] = None  # ✅ новое поле (необязательное)

class LoginData(BaseModel):
    email: str
    password: str

class UserOut(BaseModel):
    id: int
    name: str
    email: str
    phone: Optional[str] = None  # ✅ новое поле

    class Config:
        from_attributes = True

# --- Утилиты ---
def make_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=EXPIRE_DAYS)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)

def get_user_id(token: str = Depends(oauth2)) -> int:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Невалидный токен")

# --- Эндпоинты ---
@router.post("/register")
def register(data: RegisterData, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == data.email).first():
        raise HTTPException(status_code=400, detail="Email уже зарегистрирован")
    user = User(
        name=data.name,
        email=data.email,
        password=pwd.hash(data.password),
        phone=data.phone  # ✅ сохраняем телефон
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {
        "access_token": make_token(user.id),
        "token_type": "bearer",
        "user": {"id": user.id, "name": user.name, "email": user.email, "phone": user.phone}
    }

@router.post("/login")
def login(data: LoginData, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not pwd.verify(data.password, user.password):
        raise HTTPException(status_code=401, detail="Неверный email или пароль")
    return {
        "access_token": make_token(user.id),
        "token_type": "bearer",
        "user": {"id": user.id, "name": user.name, "email": user.email, "phone": user.phone}
    }

@router.get("/me", response_model=UserOut)
def me(user_id: int = Depends(get_user_id), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user