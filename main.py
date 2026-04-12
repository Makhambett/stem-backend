import os
import json
import httpx
import asyncio
from fastapi import FastAPI, HTTPException, Request, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from dotenv import load_dotenv

# ✅ Загружаем переменные окружения из .env файла
load_dotenv()

# Импорт базы данных и роутеров
from database import Base, engine
from routerss import auth, categories, orders, products, applications

# ✅ 1. Создаем таблицы БД (если нет)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="STEM Academia API")

# ✅ 2. Настройки CORS (разрешаем запросы с фронтенда)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:8000",
        "https://stem-catalog.netlify.app",
        "https://*.netlify.app",
        "https://stem-catalog.vercel.app",
        "https://*.vercel.app",
        "https://*.onrender.com",
        "*",
        "https://stem-catalog.tnysovm.workers.dev",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ 3. Читаем настройки из .env (безопасно!)
BITRIX_WEBHOOK_URL = os.getenv("BITRIX_WEBHOOK_URL")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_GROUP_CHAT_ID = os.getenv("TELEGRAM_GROUP_CHAT_ID")

# Проверка критических переменных при старте
if not all([BITRIX_WEBHOOK_URL, GROQ_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_CHAT_ID]):
    print("⚠️ Предупреждение: Не все переменные окружения загружены. Проверьте файл .env")

# ==========================================
# 📦 PYDANTIC МОДЕЛИ
# ==========================================

class ChatMessage(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    
    # Поддержка альтернативного поля 'text' для совместимости
    @validator('message', pre=True, always=True)
    def ensure_message(cls, v, values):
        if not v and values.get('text'):
            return values['text']
        return v

# ==========================================
# 📩 ФУНКЦИЯ ОТПРАВКИ В TELEGRAM
# ==========================================

async def send_to_telegram(data: dict):
    """Отправляет уведомление о заявке в Telegram группу"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_GROUP_CHAT_ID:
        print("⚠️ Telegram настройки не заданы")
        return

    text = (
        f"📥 <b>Новая заявка с сайта</b>\n\n"
        f"📦 <b>Товар:</b> {data.get('product_name', 'Общий запрос')}\n"
        f"🔖 <b>Артикул:</b> {data.get('article') or '—'}\n"
        f"👤 <b>Имя:</b> {data.get('name')}\n"
        f"📞 <b>Телефон:</b> {data.get('phone')}\n"
        f"💬 <b>Комментарий:</b> {data.get('comment') or '—'}\n"
        f"🔗 <b>Ссылка:</b> {data.get('product_url') or '—'}"
    )

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": TELEGRAM_GROUP_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                },
                timeout=10
            )
            if response.status_code == 200:
                print(f"📩 Telegram: Заявка отправлена")
            else:
                print(f"❌ Telegram ошибка: {response.text}")
    except Exception as e:
        print(f"❌ Ошибка отправки в Telegram: {e}")

# ==========================================
# 🔵 ФУНКЦИЯ ОТПРАВКИ В BITRIX24
# ==========================================

async def send_to_bitrix(data: dict):
    """Отправляет заявку в Битрикс24 (создает Лид)"""
    if not BITRIX_WEBHOOK_URL:
        print("⚠️ Bitrix webhook URL not set")
        return

    url = f"{BITRIX_WEBHOOK_URL}crm.lead.add"
    
    payload = {
        "fields": {
            "TITLE": f"Заявка с сайта: {data.get('product_name', 'Общий запрос')}",
            "NAME": data.get('name', 'Не указано'),
            "PHONE": [{"VALUE": data.get('phone', ''), "VALUE_TYPE": "WORK"}],
            "COMMENTS": f"""
Товар: {data.get('product_name')}
Артикул: {data.get('article')}
Ссылка: {data.get('product_url')}
Комментарий: {data.get('comment')}
            """.strip(),
            "SOURCE_ID": "WEB",
            "SOURCE_DESCRIPTION": "Сайт STEM Academia",
            "OPENED": "Y"
        }
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                result = response.json()
                if result.get("result"):
                    print(f"✅ Битрикс24: Лид создан (ID: {result['result']})")
                else:
                    print(f"❌ Битрикс24 ошибка: {result}")
            else:
                print(f"❌ Битрикс24 HTTP {response.status_code}: {response.text}")
    except Exception as e:
        print(f"❌ Ошибка отправки в Битрикс24: {e}")

# ==========================================
# 🤖 AI CHAT ENDPOINT (GROQ + LLAMA 3.1)
# ==========================================

@app.post("/api/ai/chat")
async def ai_chat(request: Request):
    """
    Принимает сообщение от пользователя, отправляет в Groq API (Llama 3.1)
    и возвращает умный ответ.
    """
    # Логируем сырой запрос для отладки
    try:
        body = await request.json()
        print(f"🔍 Получен запрос: {body}")
    except json.JSONDecodeError:
        print("❌ Ошибка: Тело запроса не является валидным JSON")
        raise HTTPException(status_code=400, detail="Invalid JSON format")

    # Извлекаем сообщение (поддерживаем и 'message', и 'text')
    user_message = body.get("message") or body.get("text")
    
    if not user_message or not isinstance(user_message, str):
        print(f"❌ Ошибка валидации: сообщение не найдено. Получено: {body}")
        raise HTTPException(
            status_code=422, 
            detail={"error": "Поле 'message' (или 'text') обязательно и должно быть строкой"}
        )

    # Проверка ключа API
    if not GROQ_API_KEY:
        return {"reply": "⚠️ Ошибка: GROQ_API_KEY не настроен в .env"}

    # Системный промпт — "личность" и знания бота
    SYSTEM_PROMPT = """
    Ты — виртуальный помощник компании STEM Academia (Казахстан).
    Твоя задача: помогать клиентам подбирать мебель и оборудование, отвечать на вопросы о доставке и оплате.
    
    📋 ИНФОРМАЦИЯ О КОМПАНИИ:
    - Мы продаем: мебель для школ/офисов, парты, стулья, шкафы, интерактивные панели, 3D декор, лабораторное оборудование.
    - Доставка: По всему Казахстану.
    - Самовывоз: г. Астана, ул. Домалак-ана 26.
    - Телефон/WhatsApp: +7 700 039 58 77.
    - Сайт: stem-academia.kz
    
    💬 ПРАВИЛА ОБЩЕНИЯ:
    - Отвечай кратко, вежливо и по делу (максимум 3-4 предложения).
    - Если не знаешь точного ответа — предложи написать менеджеру в WhatsApp.
    - Не выдумывай цены и наличие, если их нет в вопросе.
    - Поддерживай русский и казахский языки (отвечай на том же, на котором спросили).
    - Если клиент спрашивает про конкретный товар — предложи перейти в каталог.
    """

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_message}
                    ],
                    "temperature": 0.5,
                    "max_tokens": 300
                },
                timeout=15.0
            )
            
            if response.status_code == 200:
                result = response.json()
                reply = result["choices"][0]["message"]["content"].strip()
                return {"reply": reply}
            else:
                print(f"❌ Groq API error: {response.status_code} - {response.text}")
                return {"reply": "⚠️ ИИ временно недоступен, попробуйте позже."}
                
    except Exception as e:
        print(f"❌ Ошибка AI-обработчика: {e}")
        return {"reply": "❌ Произошла ошибка соединения. Попробуйте ещё раз."}

# ==========================================
# 🚀 РОУТЕРЫ
# ==========================================

app.include_router(products.router, prefix="/api/products", tags=["products"])
app.include_router(categories.router, prefix="/api/categories", tags=["categories"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(applications.router, prefix="/api/applications", tags=["applications"])

# ==========================================
# 🏠 ROOT ENDPOINT
# ==========================================

@app.get("/")
def root():
    return {
        "message": "STEM Academia API работает 🚀",
        "status": "ok",
        "services": {
            "database": "connected",
            "telegram": "configured" if TELEGRAM_BOT_TOKEN else "not set",
            "bitrix24": "configured" if BITRIX_WEBHOOK_URL else "not set",
            "ai_chat": "configured" if GROQ_API_KEY else "not set"
        }
    }