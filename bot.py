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

    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        if star_id:
            q = "SELECT type, file_id, caption FROM content WHERE star_id = ?"
            params = (int(star_id),)
        else:
            q = "SELECT type, file_id, caption FROM content WHERE category_id = ?"
            params = (int(category_id),)
        async with db.execute(q, params) as cur:
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
                                 (data["name"], data.get("hashtag"), data.get("photo_url")))
            elif action == "edit_star":
                await db.execute("UPDATE stars SET name=?, hashtag=?, photo_url=? WHERE id=?",
                                 (data["name"], data.get("hashtag"), data.get("photo_url"), int(data["id"])))
            elif action == "delete_star":
                await db.execute("DELETE FROM stars WHERE id=?", (int(data["id"]),))

            elif action == "add_category":
                await db.execute("INSERT INTO categories (name) VALUES (?)", (data["name"],))
            elif action == "edit_category":
                await db.execute("UPDATE categories SET name=? WHERE id=?", (data["name"], int(data["id"])))
            elif action == "delete_category":
                await db.execute("DELETE FROM categories WHERE id=?", (int(data["id"]),))

            elif action == "add_paid":
                await db.execute("INSERT INTO paid_content (type, file_id, caption) VALUES (?,?,?)",
                                 (data["type"], data["file_id"], data.get("caption")))
            elif action == "edit_paid":
                await db.execute("UPDATE paid_content SET caption=? WHERE id=?", (data.get("caption"), int(data["id"])))
            elif action == "delete_paid":
                await db.execute("DELETE FROM paid_content WHERE id=?", (int(data["id"]),))

            await db.commit()
            return web.json_response({"success": True, "message": "Операция выполнена"})
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

@router.message(F.web_app_data)
async def webapp_data_handler(message: Message):
    try:
        data = json.loads(message.web_app_data.data)
        if data.get("action") == "add_comment":
            async with aiosqlite.connect(DB_NAME) as db:
                await db.execute("INSERT INTO comments (content_id, nickname, text, user_id) VALUES (?,?,?,?)",
                                 (data["content_id"], data["nickname"], data["text"], message.from_user.id))
                await db.commit()
    except Exception as e:
        logging.error(e)

# channel_post_handler (авто-синхронизация из канала) — оставлен как был
@router.channel_post()
async def channel_post_handler(message: Message):
    # ... (твой оригинальный код обработки постов из канала)
    if not message.photo and not message.video: return
    # (вставь сюда свой прежний channel_post_handler если он отличается — он уже работает)
    pass

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
    BASE_URL = os.getenv("RENDER_EXTERNAL_URL") or "https://px-only.onrender.com"
    webhook_url = f"{BASE_URL}{WEBHOOK_PATH}"

    webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=WEBHOOK_SECRET)
    webhook_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', int(os.getenv("PORT", 8080)))
    await site.start()

    await bot.set_webhook(url=webhook_url, secret_token=WEBHOOK_SECRET, drop_pending_updates=True)

    try:
        while True: await asyncio.sleep(3600)
    finally:
        await bot.delete_webhook()
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
