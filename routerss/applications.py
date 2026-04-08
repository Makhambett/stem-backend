from datetime import datetime
import os

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
    comment: str | None = None
    product_name: str
    article: str | None = None


@router.post("/")
async def create_application(data: ApplicationCreate, db: Session = Depends(get_db)):
    digits = "".join(ch for ch in data.phone if ch.isdigit())
    if len(digits) < 10 or len(digits) > 15:
        raise HTTPException(status_code=400, detail="Некорректный номер телефона")

    db_app = models.Application(
        name=data.name,
        phone=data.phone,
        comment=data.comment,
        product_name=data.product_name,
        article=data.article,
        status="new",
        created_at=str(datetime.now()),
    )
    db.add(db_app)
    db.commit()
    db.refresh(db_app)

    text = (
        f"📥 <b>Новая заявка с сайта!</b>\n\n"
        f"👤 Имя: {data.name}\n"
        f"📞 Телефон: {data.phone}\n"
        f"📦 Товар: {data.product_name}\n"
        f"🔖 Артикул: {data.article or '—'}\n"
        f"💬 Комментарий: {data.comment or '—'}\n\n"
        f"🆔 ID заявки: #{db_app.id}"
    )

    if BOT_TOKEN and GROUP_CHAT_ID:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": GROUP_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                },
            )
            response.raise_for_status()

    return {"status": "ok", "id": db_app.id}


@router.get("/")
def get_applications(db: Session = Depends(get_db)):
    return db.query(models.Application).all()


@router.patch("/{app_id}/status")
def update_status(app_id: int, status: str, db: Session = Depends(get_db)):
    app = db.query(models.Application).filter(models.Application.id == app_id).first()

    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    app.status = status
    db.commit()
    db.refresh(app)

    return {"status": "updated", "application": app.id, "new_status": app.status}