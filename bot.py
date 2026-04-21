import asyncio
import logging
import json
import os

import aiosqlite
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.utils.web_app import safe_parse_webapp_init_data
from aiohttp import web
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# ====================== НАСТРОЙКИ ======================
BOT_TOKEN = os.getenv("BOT_TOKEN", "6162146726:AAGjWYQlcPXXp4sdh5BkfIRCiHDhBqNaTFs")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://px-only.onrender.com/static/index.html")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "my-super-secret-px-2026")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "1423028519"))

DB_NAME = "database.db"

logging.basicConfig(level=logging.INFO)

# ====================== БАЗА ДАННЫХ ======================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS stars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                hashtag TEXT UNIQUE,
                photo_url TEXT,
                description TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        """)
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
        await db.execute("""
            CREATE TABLE IF NOT EXISTS paid_content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                file_id TEXT NOT NULL,
                caption TEXT
            )
        """)
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


# ====================== ПОМОЩНИК ДЛЯ FILE_URL ======================
async def get_file_url(file_id: str) -> str | None:
    """Возвращает прямую ссылку на файл через Telegram Bot API"""
    if not file_id:
        return None
    try:
        file_info = await bot.get_file(file_id)
        return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
    except Exception as e:
        logging.error(f"get_file_url error for {file_id}: {e}")
        return None


# ====================== WEBAPP API ======================
async def api_handler(request, table_name):
    try:
        data = await request.post()
        safe_parse_webapp_init_data(token=BOT_TOKEN, init_data=data.get("_auth"))
    except Exception:
        return web.json_response({"error": "Unauthorized"}, status=401)

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        if table_name == "stars":
            async with db.execute("SELECT id, name, hashtag, photo_url FROM stars ORDER BY name") as cur:
                items = [dict(r) async for r in cur]
        elif table_name == "categories":
            async with db.execute("SELECT id, name FROM categories ORDER BY name") as cur:
                items = [dict(r) async for r in cur]
        elif table_name == "paid":
            async with db.execute("SELECT id, type, file_id, caption FROM paid_content ORDER BY id DESC") as cur:
                rows = [dict(r) async for r in cur]
            for row in rows:
                row["file_url"] = await get_file_url(row["file_id"])
            items = rows
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
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT nickname, text, created_at as time FROM comments WHERE content_id=? ORDER BY created_at DESC",
            (content_id,)
        ) as cur:
            comments = [dict(r) async for r in cur]
    return web.json_response(comments)


async def api_content(request):
    try:
        data = await request.post()
        safe_parse_webapp_init_data(token=BOT_TOKEN, init_data=data.get("_auth"))
        star_id = data.get("star_id")
        category_id = data.get("category_id")
    except Exception:
        return web.json_response({"error": "Unauthorized"}, status=401)

    if not star_id and not category_id:
        return web.json_response([])

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        if star_id:
            query = "SELECT type, file_id, caption FROM content WHERE star_id = ?"
            params = (int(star_id),)
        else:
            query = "SELECT type, file_id, caption FROM content WHERE category_id = ?"
            params = (int(category_id),)

        async with db.execute(query, params) as cur:
            rows = [dict(r) async for r in cur]

        for row in rows:
            row["file_url"] = await get_file_url(row["file_id"])

        return web.json_response(rows)


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
    await message.answer("Добро пожаловать в PX 🔥", reply_markup=kb)


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


@router.channel_post()
async def channel_post_handler(message: Message):
    if not message.photo and not message.video:
        return

    try:
        caption = message.caption or ""
        text_lower = caption.lower()
        hashtags = [tag for tag in text_lower.split() if tag.startswith("#")]

        file_id = None
        media_type = None

        if message.photo:
            file_id = message.photo[-1].file_id
            media_type = "photo"
        elif message.video:
            file_id = message.video.file_id
            media_type = "video"

        async with aiosqlite.connect(DB_NAME) as db:
            db.row_factory = aiosqlite.Row

            # Платный контент
            if any(word in text_lower for word in ["платное", "#paid", "#exclusive", "exclusive", "только для подписки"]):
                await db.execute(
                    "INSERT INTO paid_content (type, file_id, caption) VALUES (?, ?, ?)",
                    (media_type, file_id, caption)
                )
                await db.commit()
                logging.info(f"Сохранён платный контент: {media_type}")
                return

            # Звезда
            star_id = None
            for tag in hashtags:
                async with db.execute("SELECT id FROM stars WHERE hashtag = ? COLLATE NOCASE", (tag,)) as cur:
                    row = await cur.fetchone()
                    if row:
                        star_id = row["id"]
                        break

            if star_id:
                await db.execute(
                    "INSERT INTO content (type, file_id, caption, star_id) VALUES (?, ?, ?, ?)",
                    (media_type, file_id, caption, star_id)
                )
                await db.commit()
                logging.info(f"Сохранён контент звезды (star_id={star_id})")
                return

            # Категория
            cat_id = None
            for tag in hashtags:
                async with db.execute("SELECT id FROM categories WHERE name = ? COLLATE NOCASE", (tag,)) as cur:
                    row = await cur.fetchone()
                    if row:
                        cat_id = row["id"]
                        break

            if cat_id:
                await db.execute(
                    "INSERT INTO content (type, file_id, caption, category_id) VALUES (?, ?, ?, ?)",
                    (media_type, file_id, caption, cat_id)
                )
                await db.commit()
                logging.info(f"Сохранён контент категории (cat_id={cat_id})")

    except Exception as e:
        logging.error(f"Ошибка при обработке channel_post: {e}")


# ====================== ЗАПУСК ======================
async def main():
    await init_db()

    app = web.Application()

    # API-роуты для WebApp
    app.router.add_post('/api/stars', lambda r: api_handler(r, "stars"))
    app.router.add_post('/api/categories', lambda r: api_handler(r, "categories"))
    app.router.add_post('/api/paid', lambda r: api_handler(r, "paid"))
    app.router.add_post('/api/comments', api_comments)
    app.router.add_post('/api/content', api_content)   # ← Новый роут

    # Статика
    static_dir = os.path.join(os.getcwd(), "static")
    if os.path.exists(static_dir):
        app.router.add_static('/static/', static_dir, name='static')
        logging.info("Static files served from /static/")
    else:
        logging.warning("Папка static не найдена!")

    # Webhook
    WEBHOOK_PATH = "/webhook"
    BASE_URL = os.getenv("RENDER_EXTERNAL_URL") or "https://px-only.onrender.com"
    webhook_url = f"{BASE_URL}{WEBHOOK_PATH}"

    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET
    )
    webhook_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

    logging.info(f"🚀 Сервер запущен на порту {port}")
    logging.info(f"✅ Webhook URL: {webhook_url}")

    await bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        drop_pending_updates=True,
        allowed_updates=["message", "channel_post", "web_app_data"]
    )
    logging.info("✅ Webhook успешно установлен")

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await bot.delete_webhook()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
