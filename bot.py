import asyncio
import logging
import json
import os
import sys

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
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logging.error("BOT_TOKEN is not set!")
    sys.exit(1)

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://px-only.onrender.com/static/index.html")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "my-super-secret-px-2026")
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "1423028519"))

DB_NAME = "database.db"

logging.basicConfig(level=logging.INFO)

# ====================== БАЗА ДАННЫХ ======================
async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS stars (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, hashtag TEXT UNIQUE, photo_url TEXT, description TEXT)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS content (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, file_id TEXT NOT NULL, caption TEXT, star_id INTEGER, category_id INTEGER)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS paid_content (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL, file_id TEXT NOT NULL, caption TEXT)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS comments (id INTEGER PRIMARY KEY AUTOINCREMENT, content_id INTEGER NOT NULL, nickname TEXT NOT NULL, text TEXT NOT NULL, user_id INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        await db.commit()

async def get_file_url(file_id: str) -> str | None:
    if not file_id: return None
    try:
        file = await bot.get_file(file_id)
        return f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
    except Exception as e:
        logging.error(f"get_file_url error: {e}")
        return None

# ====================== API ======================
async def api_handler(request, table_name):
    try:
        data = await request.post()
        safe_parse_webapp_init_data(token=BOT_TOKEN, init_data=data.get("_auth"))
    except Exception:
        return web.json_response({"error": "Unauthorized"}, status=401)

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        if table_name == "stars":
            async with db.execute("SELECT * FROM stars ORDER BY name") as cur:
                items = [dict(r) async for r in cur]
        elif table_name == "categories":
            async with db.execute("SELECT * FROM categories ORDER BY name") as cur:
                items = [dict(r) async for r in cur]
        elif table_name == "paid":
            async with db.execute("SELECT * FROM paid_content ORDER BY id DESC") as cur:
                rows = [dict(r) async for r in cur]
            for r in rows:
                r["file_url"] = await get_file_url(r["file_id"])
            items = rows
        else:
            items = []
    return web.json_response(items)

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
        query = "SELECT type, file_id, caption FROM content WHERE star_id = ?" if star_id else "SELECT type, file_id, caption FROM content WHERE category_id = ?"
        params = (int(star_id or category_id),)
        async with db.execute(query, params) as cur:
            rows = [dict(r) async for r in cur]
        for r in rows:
            r["file_url"] = await get_file_url(r["file_id"])
        return web.json_response(rows)

async def api_admin_manage(request):
    try:
        data = await request.post()
        safe_parse_webapp_init_data(token=BOT_TOKEN, init_data=data.get("_auth"))
        action = data.get("action")
    except Exception:
        return web.json_response({"error": "Unauthorized"}, status=401)

    async with aiosqlite.connect(DB_NAME) as db:
        try:
            if action == "add_star":
                await db.execute("INSERT INTO stars (name, hashtag, photo_url) VALUES (?,?,?)", 
                                 (data.get("name"), data.get("hashtag"), data.get("photo_url")))
            elif action == "add_category":
                await db.execute("INSERT INTO categories (name) VALUES (?)", (data.get("name"),))
            await db.commit()
            return web.json_response({"success": True, "message": "Успешно добавлено"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

# ====================== БОТ ======================
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

@router.message(Command("start"))
async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Открыть PX Menu", web_app=WebAppInfo(url=WEBAPP_URL))]])
    await message.answer("Добро пожаловать в PX 🔥", reply_markup=kb)

# ====================== ЗАПУСК ======================
async def main():
    await init_db()
    app = web.Application()

    app.router.add_post('/api/stars', lambda r: api_handler(r, "stars"))
    app.router.add_post('/api/categories', lambda r: api_handler(r, "categories"))
    app.router.add_post('/api/paid', lambda r: api_handler(r, "paid"))
    app.router.add_post('/api/content', api_content)
    app.router.add_post('/api/admin/manage', api_admin_manage)

    static_dir = os.path.join(os.getcwd(), "static")
    if os.path.exists(static_dir):
        app.router.add_static('/static/', static_dir)

    WEBHOOK_PATH = "/webhook"
    BASE_URL = os.getenv("RENDER_EXTERNAL_URL")
    if not BASE_URL:
        BASE_URL = "https://px-only.onrender.com"
    webhook_url = f"{BASE_URL}{WEBHOOK_PATH}"

    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET)
    webhook_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

    logging.info(f"🚀 Сервер запущен на порту {port}")
    logging.info(f"✅ Webhook URL: {webhook_url}")

    await bot.set_webhook(url=webhook_url, secret_token=WEBHOOK_SECRET, drop_pending_updates=True)

    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await bot.delete_webhook()
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
