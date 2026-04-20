import asyncio
import logging
import json
from urllib.parse import quote

import aiosqlite
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    Message, InlineKeyboardMarkup, InlineKeyboardButton,
    WebAppInfo, WebAppData
)
from aiogram.utils.web_app import safe_parse_webapp_init_data
from aiohttp import web

# ====================== НАСТРОЙКИ ======================
BOT_TOKEN = "6162146726:AAGjWYQlcPXXp4sdh5BkfIRCiHDhBqNaTFs"                    # ← Замени!
PERSONAL_USERNAME = "PX_MrM"              # ← твой ник без @
ADMIN_USER_ID = 1423028519                        # ← твой Telegram ID

DB_NAME = "database.db"
WEBAPP_URL = "https://px-only.onrender.com/static/index.html"   # ← Замени после деплоя!

logging.basicConfig(level=logging.INFO)

# ====================== БАЗА ДАННЫХ ======================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Звёзды
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                hashtag TEXT UNIQUE,
                photo_url TEXT,
                description TEXT
            )
        """)
        # Категории
        await db.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        """)
        # Обычный контент
        await db.execute("""
            CREATE TABLE IF NOT EXISTS content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                file_id TEXT NOT NULL,
                caption TEXT,
                star_id INTEGER,
                category_id INTEGER,
                FOREIGN KEY(star_id) REFERENCES stars(id),
                FOREIGN KEY(category_id) REFERENCES categories(id)
            )
        """)
        # Платный контент
        await db.execute("""
            CREATE TABLE IF NOT EXISTS paid_content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                file_id TEXT NOT NULL,
                caption TEXT
            )
        """)
        # Анонимные комментарии
        await db.execute("""
            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_id INTEGER NOT NULL,
                nickname TEXT NOT NULL,
                text TEXT NOT NULL,
                user_id INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


# ====================== WEBAPP API ======================
async def api_handler(request, table_name):
    try:
        data = await request.post()
        safe_parse_webapp_init_data(token=BOT_TOKEN, init_data=data.get("_auth"))
    except Exception:
        return web.json_response({"error": "Unauthorized"}, status=401)

    async with aiosqlite.connect(DB_NAME) as db:
        if table_name == "stars":
            async with db.execute("SELECT id, name, hashtag, photo_url FROM stars ORDER BY name") as cur:
                items = [dict(id=r[0], name=r[1], hashtag=r[2], photo_url=r[3]) async for r in cur]
        elif table_name == "categories":
            async with db.execute("SELECT id, name FROM categories ORDER BY name") as cur:
                items = [dict(id=r[0], name=r[1]) async for r in cur]
        elif table_name == "paid":
            async with db.execute("SELECT id, type, file_id, caption FROM paid_content") as cur:
                items = [dict(id=r[0], type=r[1], file_id=r[2], caption=r[3]) async for r in cur]
        else:
            items = []
    return web.json_response(items)


async def api_comments(request):
    try:
        data = await request.post()
        safe_parse_webapp_init_data(token=BOT_TOKEN, init_data=data.get("_auth"))
        content_id = int(data.get("content_id", 0))
    except Exception:
        return web.json_response({"error": "Unauthorized"}, status=401)

    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT nickname, text, created_at FROM comments WHERE content_id=? ORDER BY created_at DESC",
            (content_id,)
        ) as cur:
            comments = [dict(nickname=r[0], text=r[1], time=r[2]) async for r in cur]
    return web.json_response(comments)


# ====================== БОТ ======================
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher()
router = Router()
dp.include_router(router)

@router.message(Command("start"))
async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Открыть PX Menu", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])
    await message.answer("PX", reply_markup=kb)


@router.message(F.web_app_data)
async def webapp_data_handler(message: Message):
    try:
        data = json.loads(message.web_app_data.data)
        if data.get("action") == "add_comment":
            content_id = data["content_id"]
            nickname = data["nickname"]
            text = data["text"]

            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute(
                    "INSERT INTO comments (content_id, nickname, text, user_id) VALUES (?, ?, ?, ?)",
                    (content_id, nickname, text, message.from_user.id)
                )
                await db.commit()

            await message.answer(f"✅ Комментарий от {nickname} сохранён!")
    except Exception as e:
        logging.error(f"WebApp data error: {e}")


# ====================== АВТО-ЧТЕНИЕ ИЗ КАНАЛА ======================
@router.channel_post()
async def channel_post_handler(message: Message):
    if not message.photo and not message.video:
        return

    text = (message.caption or "").lower()
    hashtags = [tag for tag in text.split() if tag.startswith("#")]

    file_id = None
    media_type = None
    caption = message.caption or ""

    if message.photo:
        file_id = message.photo[-1].file_id
        media_type = "photo"
    elif message.video:
        file_id = message.video.file_id
        media_type = "video"

    async with aiosqlite.connect(DB_NAME) as db:
        # Платное
        if any(word in text for word in ["платное", "платн", "#paid", "#exclusive"]):
            await db.execute(
                "INSERT INTO paid_content (type, file_id, caption) VALUES (?, ?, ?)",
                (media_type, file_id, caption)
            )
            await db.commit()
            return

        # Звезда
        star_id = None
        for tag in hashtags:
            async with db.execute("SELECT id FROM stars WHERE hashtag = ? COLLATE NOCASE", (tag,)) as cur:
                row = await cur.fetchone()
                if row:
                    star_id = row[0]
                    break
        if star_id:
            await db.execute(
                "INSERT INTO content (type, file_id, caption, star_id) VALUES (?, ?, ?, ?)",
                (media_type, file_id, caption, star_id)
            )
            await db.commit()
            return

        # Категория
        cat_id = None
        for tag in hashtags:
            async with db.execute("SELECT id FROM categories WHERE name = ? COLLATE NOCASE", (tag,)) as cur:
                row = await cur.fetchone()
                if row:
                    cat_id = row[0]
                    break
        if cat_id:
            await db.execute(
                "INSERT INTO content (type, file_id, caption, category_id) VALUES (?, ?, ?, ?)",
                (media_type, file_id, caption, cat_id)
            )
            await db.commit()


# ====================== ЗАПУСК ======================
async def main():
    await init_db()

    # Запуск WebApp сервера
    app = web.Application()
    app.router.add_post('/api/stars', lambda r: api_handler(r, "stars"))
    app.router.add_post('/api/categories', lambda r: api_handler(r, "categories"))
    app.router.add_post('/api/paid', lambda r: api_handler(r, "paid"))
    app.router.add_post('/api/comments', api_comments)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()

    logging.info("WebApp сервер запущен на порту 8080")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
