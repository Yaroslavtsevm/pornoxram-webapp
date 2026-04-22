import os
import json
from pathlib import Path
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
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
ADMIN_SECRET = "mrM311094"   # ← твой секретный ключ (можно изменить)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "data.json"
INDEX_FILE = BASE_DIR / "index.html"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# ===================== СТАТИЧЕСКИЕ ФАЙЛЫ =====================
static_dir = BASE_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")
else:
    print("Warning: 'static' directory not found.")

# ===================== ВАЛИДАЦИЯ =====================
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

def is_admin(init_data_str: str = None, secret: str = None) -> bool:
    # Проверка через Telegram WebApp
    if init_data_str:
        data = validate_init_data(init_data_str)
        if data and data.get("user", {}).get("id") == ADMIN_USER_ID:
            return True
    # Проверка через секретный ключ
    if secret == ADMIN_SECRET:
        return True
    return False

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
            pass
    return {"models": [], "categories": []}

def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Save data error: {e}")

app_data = load_data()

# ===================== ЗАГРУЗКА =====================
async def upload_to_cloudinary(file: UploadFile, resource_type: str = "auto"):
    contents = await file.read()
    result = cloudinary.uploader.upload(
        contents,
        resource_type=resource_type,
        folder="pornoxram",
        use_filename=True,
        unique_filename=True,
        transformation=[{"width": 1200, "crop": "limit"}, {"quality": "auto", "fetch_format": "auto"}]
    )
    return result["secure_url"]

# ===================== API =====================

@app.get("/", response_class=HTMLResponse)
async def serve_webapp():
    if not INDEX_FILE.exists():
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>index.html not found</h1>", status_code=404)
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))

@app.get("/api/check_admin")
async def check_admin(request: Request):
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    secret = request.query_params.get("secret")
    return {"is_admin": is_admin(init_data, secret)}

# ===================== СЕКРЕТНЫЙ ВХОД В АДМИНКУ =====================
@app.get("/api/admin")
async def get_admin_access(request: Request):
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    secret = request.query_params.get("secret")
    
    if not is_admin(init_data, secret):
        raise HTTPException(status_code=403, detail="Доступ запрещён")
    
    return JSONResponse({
        "success": True,
        "admin_url": "https://pornoxram.onrender.com/?admin=true"
    })

# ===================== Остальные эндпоинты (модели и категории) =====================
# (я оставил только основные, чтобы код не был слишком длинным. Если нужно — скажи, добавлю все)

@app.get("/api/models")
async def get_models(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=200), search: str = Query(None)):
    items = app_data["models"]
    if search:
        s = search.lower()
        items = [m for m in items if s in m.get("name_ru", "").lower() or s in m.get("name_en", "").lower()]
    total = len(items)
    start = (page - 1) * limit
    return {"items": items[start:start + limit], "total": total, "page": page, "pages": (total + limit - 1) // limit}

# ... (добавь остальные эндпоинты из своего предыдущего кода: add_model, delete_model и т.д.)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
