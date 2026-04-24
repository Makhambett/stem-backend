from datetime import datetime
import os
import re

import httpx
import models
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db

load_dotenv()

router = APIRouter()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROUP_CHAT_ID = os.getenv("TELEGRAM_GROUP_CHAT_ID")
BITRIX_WEBHOOK_URL = os.getenv("BITRIX_WEBHOOK_URL")


class ApplicationCreate(BaseModel):
    name: str
    phone: str
    username: str | None = None
    comment: str | None = None
    product_name: str
    article: str | None = None
    product_url: str | None = None


def validate_name(name: str) -> bool:
    cleaned = name.strip()
    if len(cleaned) < 2 or len(cleaned) > 50:
        return False

    return bool(
        re.fullmatch(
            r"[A-Za-zА-Яа-яӘәҒғҚқҢңӨөҰұҮүҺһІіЁё\s\-]+",
            cleaned,
        )
    )


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


async def send_to_bitrix(data: dict):
    if not BITRIX_WEBHOOK_URL:
        print("⚠️ Bitrix webhook URL не настроен")
        return

    url = f"{BITRIX_WEBHOOK_URL.rstrip('/')}/crm.lead.add.json"

    comments = (
        f"Товар: {data.get('product_name') or '—'}\n"
        f"Артикул: {data.get('article') or '—'}\n"
        f"Ссылка: {data.get('product_url') or '—'}\n"
        f"Telegram: @{data.get('username') or 'Не указан'}\n"
        f"Комментарий клиента: {data.get('comment') or '—'}\n"
        f"ID заявки: {data.get('id') or 'N/A'}"
    )

    payload = {
        "fields": {
            "TITLE": f"Заявка с сайта: {data.get('product_name') or 'Общий запрос'}",
            "NAME": data.get("name") or "Не указано",
            "PHONE": [
                {
                    "VALUE": data.get("phone") or "",
                    "VALUE_TYPE": "WORK",
                }
            ],
            "COMMENTS": comments,
            "SOURCE_ID": "WEB",
            "SOURCE_DESCRIPTION": "Сайт STEM Academia",
            "OPENED": "Y",
        }
    }

    print(f"🚀 Отправка в Битрикс: {url}")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10)
            print(f"✅ Битрикс ответ: {response.status_code} | {response.text}")
    except Exception as e:
        print(f"❌ Ошибка отправки в Битрикс: {e}")


async def send_to_telegram(data: dict, app_id: int):
    if not BOT_TOKEN or not GROUP_CHAT_ID:
        print("⚠️ Telegram токен или chat_id не настроены")
        return

    username_line = (
        f"🔗 <b>Username:</b> @{data.get('username')}\n"
        if data.get("username")
        else ""
    )

    text = (
        f"📥 <b>Новая заявка с сайта</b>\n"
        f"🆔 <b>ID:</b> #{app_id}\n"
        f"📌 <b>Статус:</b> 🟡 Новая\n"
        f"🕒 <b>Время:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"📦 <b>Товар:</b> {data.get('product_name') or '—'}\n"
        f"🔖 <b>Артикул:</b> {data.get('article') or '—'}\n"
        f"🌐 <b>Ссылка:</b> {data.get('product_url') or '—'}\n"
        f"👤 <b>Имя:</b> {data.get('name') or '—'}\n"
        f"📞 <b>Телефон:</b> {data.get('phone') or '—'}\n"
        f"{username_line}"
        f"💬 <b>Комментарий:</b> {data.get('comment') or '—'}"
    )

    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": GROUP_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
        print(f"📩 Telegram: Заявка #{app_id} отправлена")
    except Exception as e:
        print(f"❌ Ошибка отправки в Telegram: {e}")


@router.post("/")
async def create_application(
    data: ApplicationCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if not validate_name(data.name):
        raise HTTPException(status_code=400, detail="Некорректное имя")

    normalized_phone = normalize_phone(data.phone)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    db_app = models.Application(
        name=data.name.strip(),
        phone=normalized_phone,
        username=(data.username or "").replace("@", "").strip() or None,
        comment=data.comment.strip() if data.comment else None,
        product_name=data.product_name.strip(),
        article=data.article.strip() if data.article else None,
        product_url=data.product_url.strip() if data.product_url else None,
        status="new",
        created_at=now,
        updated_at=now,
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


@router.get("/")
def get_applications(db: Session = Depends(get_db)):
    return db.query(models.Application).all()
