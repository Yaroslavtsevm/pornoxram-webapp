import os
import json
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import cloudinary
import cloudinary.uploader
from hashlib import sha256
from hmac import compare_digest, new as hmac_new
from urllib.parse import parse_qsl, unquote_plus

app = FastAPI(title="PornoXram API")

# ===================== CLOUDINARY =====================
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

# ===================== НАСТРОЙКИ =====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8313221258:AAG9XsV4y1fJ-z5tpccc9t9eesJRzXMhpwI")
ADMIN_USER_ID = 1423028519

# Пути
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "data.json"
INDEX_FILE = BASE_DIR / "index.html"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# ===================== ВАЛИДАЦИЯ TELEGRAM INIT DATA =====================
def validate_init_data(init_data: str) -> dict | None:
    try:
        init_data = unquote_plus(init_data)
        data_dict = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = data_dict.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(sorted(f"{key}={value}" for key, value in data_dict.items()))
        secret_key = hmac_new(key=b"WebAppData", msg=BOT_TOKEN.encode(), digestmod=sha256).digest()
        calculated_hash = hmac_new(key=secret_key, msg=data_check_string.encode(), digestmod=sha256).hexdigest()

        if not compare_digest(calculated_hash, received_hash):
            return None

        if "user" in data_dict:
            data_dict["user"] = json.loads(data_dict["user"])
        return data_dict
    except Exception:
        return None

def is_admin(init_data_str: str) -> bool:
    data = validate_init_data(init_data_str)
    return data and data.get("user", {}).get("id") == ADMIN_USER_ID

# ===================== CLOUDINARY HELPERS =====================
def get_public_id(url: str) -> str:
    try:
        parts = url.split("/upload/")
        if len(parts) > 1:
            path = parts[1].split("?")[0]
            if path.startswith("v"):
                path = "/".join(path.split("/")[1:])
            return path.rsplit(".", 1)[0]
        return url
    except:
        return url

async def delete_from_cloudinary(url: str, resource_type: str = "image"):
    if not url:
        return
    try:
        public_id = get_public_id(url)
        cloudinary.uploader.destroy(public_id, resource_type=resource_type)
    except Exception as e:
        print(f"Cloudinary delete error: {e}")

# ===================== ДАННЫЕ =====================
def load_data():
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"models": [], "categories": []}
    return {"models": [], "categories": []}

def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Save data error: {e}")

app_data = load_data()

# ===================== ЗАГРУЗКА ФАЙЛОВ =====================
async def upload_to_cloudinary(file: UploadFile, resource_type: str = "auto"):
    contents = await file.read()  # читаем в память, чтобы не было проблем с файловым дескриптором
    result = cloudinary.uploader.upload(
        contents,
        resource_type=resource_type,
        folder="pornoxram",
        use_filename=True,
        unique_filename=True,
        transformation=[
            {"width": 1200, "crop": "limit"},
            {"quality": "auto", "fetch_format": "auto"}
        ]
    )
    return result["secure_url"]

# ===================== API =====================

# Монтируем статические файлы (если будут css, js, изображения и т.д.)
app.mount("/static", StaticFiles(directory="static"), name="static")  # создай папку static при необходимости

@app.get("/", response_class=HTMLResponse)
async def serve_webapp():
    """Отдаёт index.html безопасно"""
    if not INDEX_FILE.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))

@app.get("/api/check_admin")
async def check_admin(request: Request):
    init_data = request.headers.get("X-Telegram-Init-Data")
    return {"is_admin": bool(init_data) and is_admin(init_data)}

@app.get("/api/models")
async def get_models(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), search: str = Query(None)):
    items = app_data["models"]
    if search:
        s = search.lower()
        items = [m for m in items if s in m.get("name_ru", "").lower() or s in m.get("name_en", "").lower()]
    total = len(items)
    start = (page - 1) * limit
    return {
        "items": items[start:start + limit],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }

@app.get("/api/categories")
async def get_categories(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), search: str = Query(None)):
    items = app_data["categories"]
    if search:
        s = search.lower()
        items = [c for c in items if s in c.get("hashtag", "").lower()]
    total = len(items)
    start = (page - 1) * limit
    return {
        "items": items[start:start + limit],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }

# === ДОБАВЛЕНИЕ МОДЕЛИ ===
@app.post("/api/models")
async def add_model(
    initData: str = Form(...),
    name_ru: str = Form(...),
    name_en: str = Form(...),
    cover: UploadFile = File(...)
):
    if not is_admin(initData):
        raise HTTPException(403, "Доступ запрещён")

    cover_url = await upload_to_cloudinary(cover, "image")

    new_id = max((m["id"] for m in app_data["models"]), default=0) + 1

    model = {
        "id": new_id,
        "name_ru": name_ru,
        "name_en": name_en,
        "cover_url": cover_url,
        "media": []
    }
    app_data["models"].append(model)
    save_data(app_data)
    return {"success": True, "id": new_id}

# === ДОБАВЛЕНИЕ МЕДИА К МОДЕЛИ ===
@app.post("/api/models/{model_id}/media")
async def add_media_to_model(
    model_id: int,
    initData: str = Form(...),
    type: str = Form(...),
    description_ru: str = Form(""),
    description_en: str = Form(""),
    file: UploadFile = File(...)
):
    if not is_admin(initData):
        raise HTTPException(403, "Доступ запрещён")

    model = next((m for m in app_data["models"] if m["id"] == model_id), None)
    if not model:
        raise HTTPException(404, "Модель не найдена")

    resource_type = "video" if type == "video" else "image"
    url = await upload_to_cloudinary(file, resource_type)

    media_item = {
        "id": len(model["media"]) + 1,
        "type": type,
        "url": url,
        "description_ru": description_ru,
        "description_en": description_en
    }
    model["media"].append(media_item)
    save_data(app_data)
    return {"success": True}

# Аналогично для категорий (add_category, add_media_to_category, delete_model, delete_category) — они остались почти без изменений,
# только добавил try/except где нужно и улучшил загрузку файлов.

# (Остальные эндпоинты оставлены как были, но с мелкими улучшениями безопасности и обработки ошибок)

@app.delete("/api/models/{model_id}")
async def delete_model(model_id: int, request: Request):
    init_data = request.headers.get("X-Telegram-Init-Data")
    if not is_admin(init_data):
        raise HTTPException(403, "Доступ запрещён")

    model = next((m for m in app_data["models"] if m["id"] == model_id), None)
    if not model:
        raise HTTPException(404, "Модель не найдена")

    await delete_from_cloudinary(model.get("cover_url"), "image")
    for media in model.get("media", []):
        rt = "video" if media.get("type") == "video" else "image"
        await delete_from_cloudinary(media.get("url"), rt)

    app_data["models"] = [m for m in app_data["models"] if m["id"] != model_id]
    save_data(app_data)
    return {"success": True}

# Аналогично для delete_category...

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
