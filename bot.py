import os
import json
from pathlib import Path
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import cloudinary
import cloudinary.uploader
from hashlib import sha256
from hmac import compare_digest, new as hmac_new
from urllib.parse import parse_qsl, unquote_plus

app = FastAPI(title="PX Models", version="2.0")

# ===================== CLOUDINARY =====================
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

# ===================== НАСТРОЙКИ =====================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_USER_ID = 1423028519
CHANNEL_LINK = "https://t.me/+u8svaG24-xo5MDMy"

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "data.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# ===================== ВАЛИДАЦИЯ TELEGRAM INIT DATA =====================
def validate_init_data(init_data: str) -> dict | None:
    if not init_data:
        return None
    try:
        init_data = unquote_plus(init_data)
        data_dict = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = data_dict.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(sorted(f"{k}={v}" for k, v in data_dict.items()))
        secret_key = hmac_new(b"WebAppData", BOT_TOKEN.encode(), sha256).digest()
        calculated_hash = hmac_new(secret_key, data_check_string.encode(), sha256).hexdigest()

        if not compare_digest(calculated_hash, received_hash):
            return None

        if "user" in data_dict:
            data_dict["user"] = json.loads(data_dict["user"])
        return data_dict
    except Exception as e:
        print(f"InitData validation error: {e}")
        return None

def is_admin(init_data_str: str) -> bool:
    data = validate_init_data(init_data_str)
    return data and data.get("user", {}).get("id") == ADMIN_USER_ID

# ===================== ДАННЫЕ =====================
def load_data():
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"models": []}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

app_data = load_data()

# ===================== СТАТИКА =====================
static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")

# ===================== РОУТЫ =====================
@app.get("/", response_class=HTMLResponse)
async def serve_webapp():
    index_path = BASE_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>index.html not found</h1>", 404)
    return HTMLResponse(index_path.read_text(encoding="utf-8"))

@app.get("/api/check_admin")
async def check_admin(request: Request):
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    return {"is_admin": is_admin(init_data)}

@app.get("/api/models")
async def get_models(search: str = Query(None, max_length=100)):
    items = app_data["models"]
    if search:
        s = search.lower()
        items = [m for m in items if s in str(m.get("name_ru", "")).lower() or 
                                      s in str(m.get("hashtags", "")).lower()]
    return {"items": items, "total": len(items)}

@app.post("/api/models")
async def add_model(
    initData: str = Form(...),
    name_ru: str = Form(...),
    hashtags: str = Form(""),
    cover: UploadFile = File(...)
):
    if not is_admin(initData):
        raise HTTPException(403, "Доступ запрещён")

    # Загрузка в Cloudinary
    result = cloudinary.uploader.upload(
        await cover.read(),
        folder="pornoxram",
        resource_type="image",
        transformation=[{"width": 1200, "crop": "limit"}, {"quality": "auto"}]
    )

    new_id = max((m.get("id", 0) for m in app_data["models"]), default=0) + 1

    model = {
        "id": new_id,
        "name_ru": name_ru.strip(),
        "hashtags": hashtags.strip() or f"#{name_ru.replace(' ', '')}",
        "cover_url": result["secure_url"],
        "media": []
    }

    app_data["models"].append(model)
    save_data(app_data)

    return {"success": True, "message": "Модель добавлена успешно!"}

@app.delete("/api/models/{model_id}")
async def delete_model(model_id: int, request: Request):
    if not is_admin(request.headers.get("X-Telegram-Init-Data", "")):
        raise HTTPException(403, "Доступ запрещён")

    original = len(app_data["models"])
    app_data["models"] = [m for m in app_data["models"] if m["id"] != model_id]

    if len(app_data["models"]) == original:
        raise HTTPException(404, "Модель не найдена")

    save_data(app_data)
    return {"success": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
