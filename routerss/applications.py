from datetime import datetime
import os
import re
import asyncio

import httpx
import models
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db

load_dotenv()

router = APIRouter()

# Telegram настройки
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROUP_CHAT_ID = os.getenv("TELEGRAM_GROUP_CHAT_ID")

# ✅ Bitrix24 Webhook
BITRIX_WEBHOOK_URL = os.getenv("BITRIX_WEBHOOK_URL")

class ApplicationCreate(BaseModel):
    name: str
    phone: str
    username: str | None = None
    comment: str | None = None
    product_name: str
    article: str | None = None
    product_url: str | None = None

class TakeApplication(BaseModel):
    manager_id: int
    manager_name: str

# ==========================================
# ВАЛИДАЦИЯ И ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==========================================

def validate_name(name: str) -> bool:
    cleaned = name.strip()
    if len(cleaned) < 2 or len(cleaned) > 50:
        return False
    return bool(re.fullmatch(r"[A-Za-zА-Яа-яӘәҒғҚқҢңӨөҰұҮүҺһІіЁё\s\-]+", cleaned))

def normalize_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) < 11 or len(digits) > 15:
        raise HTTPException(status_code=400, detail="Некорректный номер телефона")
    if len(digits) == 11 and digits.startswith("7"):
        return f"+7 ({digits[1:4]}) {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"
    return f"+{digits}"

# ==========================================
# ОТПРАВКА В BITRIX24
# ==========================================

async def send_to_bitrix(data: dict):
    \"\"\"Отправляет заявку в Битрикс24 (создает Лид)\"\"\"
    if not BITRIX_WEBHOOK_URL:
        print("⚠️ Bitrix webhook URL не настроен")
        return

    # ✅ Добавляем .json для корректного REST-вызова
    url = f"{BITRIX_WEBHOOK_URL.rstrip('/')}/crm.lead.add.json"
    
    payload = {
        "fields": {
            "TITLE": f"Заявка с сайта: {data.get('product_name', 'Общий запрос')}",
            "NAME": data.get('name', 'Не указано'),
            "PHONE": [{"VALUE": data.get('phone', ''), "VALUE_TYPE": "WORK"}],
            "COMMENTS": (
                f"Товар: {data.get('product_name')}\
"
                f"Артикул: {data.get('article') or '—'}\
"
                f"Ссылка: {data.get('product_url') or '—'}\
"
                f"Telegram: @{data.get('username') if data.get('username') else 'Не указан'}\
"
                f"Комментарий клиента: {data.get('comment', '—')}\
"
                f"ID заявки: {data.get('id', 'N/A')}"
            ),
            "SOURCE_ID": "WEB",
            "SOURCE_DESCRIPTION": "Сайт STEM Academia",
            "OPENED": "Y"
        }
    }

    print(f"🚀 Отправка в Битрикс: {url}")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                result = response.json()
                print(f"✅ Битрикс ответ: {result}")
            else:
                print(f"❌ Битрикс ошибка {response.status_code}: {response.text}")
    except Exception as e:
        print(f"❌ Ошибка отправки в Битрикс: {e}")

# ==========================================
# ОТПРАВКА В TELEGRAM
# ==========================================

async def send_to_telegram(data: dict, app_id: int):
    \"\"\"Отправляет уведомление в Telegram группу\"\"\"
    if not BOT_TOKEN or not GROUP_CHAT_ID:
        print("⚠️ Telegram токен или chat_id не настроены")
        return

    username_line = f"🔗 <b>Username:</b> @{data.get('username')}\
" if data.get('username') else ""
    
    text = (
        f"📥 <b>Новая заявка с сайта</b>\
\
"
        f"🆔 <b>ID:</b> #{app_id}\
"
        f"📌 <b>Статус:</b> 🟡 Новая\
"
        f"🕒 <b>Время:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\
\
"
        f"📦 <b>Товар:</b> {data.get('product_name')}\
"
        f"🔖 <b>Артикул:</b> {data.get('article') or '—'}\
"
        f"🌐 <b>Ссылка:</b> {data.get('product_url') or '—'}\
\
"
        f"👤 <b>Имя:</b> {data.get('name')}\
"
        f"📞 <b>Телефон:</b> {data.get('phone')}\
"
        f"{username_line}"
        f"💬 <b>Комментарий:</b> {data.get('comment') or '—'}"
    )

    keyboard = {
        "inline_keyboard": [
            [{"text": "✋ Взять заявку", "callback_data": f"take:{app_id}"}]
        ]
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": GROUP_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": keyboard,
                    "disable_web_page_preview": True,
                },
            )
            response.raise_for_status()
            print(f"📩 Telegram: Заявка #{app_id} отправлена")
    except Exception as e:
        print(f"❌ Ошибка отправки в Telegram: {e}")

# ==========================================
# ЭНДПОИНТЫ
# ==========================================

@router.post("/")
async def create_application(
    data: ApplicationCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    if not validate_name(data.name):
        raise HTTPException(status_code=400, detail="Некорректное имя")

    try:
        normalized_phone = normalize_phone(data.phone)
    except HTTPException as e:
        raise e

    db_app = models.Application(
        name=data.name.strip(),
        phone=normalized_phone,
        username=(data.username or "").replace("@", "").strip() or None,
        comment=data.comment.strip() if data.comment else None,
        product_name=data.product_name.strip(),
        article=data.article.strip() if data.article else None,
        product_url=data.product_url.strip() if data.product_url else None,
        status="new",
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        updated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    db.add(db_app)
    db.commit()
    db.refresh(db_app)

    app_data = {
        "id": db_app.id,
        "name": db_app.name,
        "phone": db_app.phone,
        "username": db_app.username,
        "comment": db_app.comment,
        "product_name": db_app.product_name,
        "article": db_app.article,
        "product_url": db_app.product_url,
    }

    background_tasks.add_task(send_to_bitrix, app_data)
    background_tasks.add_task(send_to_telegram, app_data, db_app.id)

    return {"status": "ok", "id": db_app.id}

@router.post("/{app_id}/take")
def take_application(app_id: int, data: TakeApplication, db: Session = Depends(get_db)):
    app = db.query(models.Application).filter(models.Application.id == app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if app.status != "new":
        raise HTTPException(status_code=400, detail="Заявка уже взята или закрыта")

    app.status = "in_progress"
    app.manager_id = data.manager_id
    app.manager_name = data.manager_name
    app.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.commit()
    db.refresh(app)
    return app

@router.get("/free")
def get_free_applications(db: Session = Depends(get_db)):
    return db.query(models.Application).filter(
        models.Application.status == "new"
    ).order_by(models.Application.id.asc()).all()

@router.get("/")
def get_applications(db: Session = Depends(get_db)):
    return db.query(models.Application).all()

@router.patch("/{app_id}/status")
def update_status(app_id: int, status: str, db: Session = Depends(get_db)):
    allowed = {"new", "in_progress", "done", "rejected"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail="Недопустимый статус")

    app = db.query(models.Application).filter(models.Application.id == app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    app.status = status
    app.updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    db.commit()
    db.refresh(app)
    return {"status": "updated", "application": app.id, "new_status": app.status}
