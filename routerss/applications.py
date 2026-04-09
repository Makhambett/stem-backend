from datetime import datetime
import os
import re

import httpx
import models
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db

load_dotenv()

router = APIRouter()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROUP_CHAT_ID = os.getenv("TELEGRAM_GROUP_CHAT_ID")


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


def status_label(status: str) -> str:
    mapping = {
        "new": "🟡 Новая",
        "in_progress": "🟠 В работе",
        "done": "✅ Закрыта",
        "rejected": "❌ Отклонена",
    }
    return mapping.get(status, status)


def build_application_text(app) -> str:
    username_line = f"🔗 <b>Username:</b> @{app.username}\n" if app.username else ""
    product_url_line = f"🌐 <b>Ссылка:</b> {app.product_url}\n" if app.product_url else ""
    return (
        f"📥 <b>Новая заявка с сайта</b>\n\n"
        f"🆔 <b>ID:</b> #{app.id}\n"
        f"📌 <b>Статус:</b> {status_label(app.status)}\n"
        f"🕒 <b>Время:</b> {app.created_at}\n\n"
        f"📦 <b>Товар:</b> {app.product_name}\n"
        f"🔖 <b>Артикул:</b> {app.article or '—'}\n"
        f"{product_url_line}"
        f"👤 <b>Имя:</b> {app.name}\n"
        f"📞 <b>Телефон:</b> {app.phone}\n"
        f"{username_line}"
        f"💬 <b>Комментарий:</b> {app.comment or '—'}"
    )


def build_take_keyboard(app_id: int):
    return {
        "inline_keyboard": [
            [{"text": "✋ Взять заявку", "callback_data": f"take:{app_id}"}]
        ]
    }


def build_action_keyboard(app_id: int):
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Закрыть", "callback_data": f"appstatus:done:{app_id}"},
                {"text": "❌ Отклонить", "callback_data": f"appstatus:rejected:{app_id}"},
            ]
        ]
    }


@router.post("/")
async def create_application(data: ApplicationCreate, db: Session = Depends(get_db)):
    if not validate_name(data.name):
        raise HTTPException(status_code=400, detail="Некорректное имя")

    normalized_phone = normalize_phone(data.phone)

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

    if BOT_TOKEN and GROUP_CHAT_ID:
        text = build_application_text(db_app)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": GROUP_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "reply_markup": build_take_keyboard(db_app.id),
                    "disable_web_page_preview": True,
                },
            )
            response.raise_for_status()

    return {"status": "ok", "id": db_app.id, "normalized_phone": normalized_phone}


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


@router.get("/manager/{manager_id}")
def get_manager_applications(manager_id: int, db: Session = Depends(get_db)):
    return db.query(models.Application).filter(
        models.Application.manager_id == manager_id
    ).all()


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