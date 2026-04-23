import os
import json
from pathlib import Path
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException, Query, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import cloudinary
import cloudinary.uploader
from hashlib import sha256
from hmac import compare_digest, new as hmac_new
from urllib.parse import parse_qsl, unquote_plus

app = FastAPI(title="PX Models API")

# ===================== CLOUDINARY =====================
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "8313221258:AAG9XsV4y1fJ-z5tpccc9t9eesJRzXMhpwI")
ADMIN_USER_ID = 1423028519

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_FILE = DATA_DIR / "data.json"
INDEX_FILE = BASE_DIR / "index.html"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# ===================== ВАЛИДАЦИЯ TELEGRAM INIT DATA =====================
def validate_init_data(init_data: str):
    try:
        init_data = unquote_plus(init_data)
        data_dict = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = data_dict.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(sorted(f"{k}={v}" for k, v in data_dict.items()))
        secret_key = hmac_new(key=b"WebAppData", msg=BOT_TOKEN.encode(), digestmod=sha256).digest()
        calculated_hash = hmac_new(key=secret_key, msg=data_check_string.encode(), digestmod=sha256).hexdigest()

        if not compare_digest(calculated_hash, received_hash):
            return None

        if "user" in data_dict:
            data_dict["user"] = json.loads(data_dict["user"])
        return data_dict
    except Exception:
        return None

def get_current_admin(init_data: str = Form(alias="init_data")):
    data = validate_init_data(init_data)
    if not data or data.get("user", {}).get("id") != ADMIN_USER_ID:
        raise HTTPException(status_code=403, detail="Доступ запрещён. Вы не админ.")
    return data

# ===================== ЗАГРУЗКА ФАЙЛОВ =====================
async def upload_to_cloudinary(file: UploadFile):
    contents = await file.read()
    result = cloudinary.uploader.upload(
        contents,
        resource_type="image",
        folder="pornoxram",
        use_filename=True,
        unique_filename=True,
        transformation=[{"width": 1200, "crop": "limit"}, {"quality": "auto", "fetch_format": "auto"}]
    )
    return result["secure_url"]

# ===================== ДАННЫЕ =====================
def load_data():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except:
            pass
    return {"models": []}

def save_data(data):
    DATA_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

app_data = load_data()

# ===================== СТАТИКА =====================
if (BASE_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory="static"), name="static")

# ===================== РОУТЫ =====================
@app.get("/", response_class=HTMLResponse)
async def serve_webapp():
    if not INDEX_FILE.exists():
        return HTMLResponse("<h1 style='color:red;text-align:center;margin-top:100px;'>index.html not found</h1>", 404)
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))

@app.post("/api/models")
async def add_model(
    name_ru: str = Form(...),
    hashtags: str = Form(""),
    cover: UploadFile = File(...),
    admin_data: dict = Depends(get_current_admin)
):
    cover_url = await upload_to_cloudinary(cover)

    new_id = max((m.get("id", 0) for m in app_data["models"]), default=0) + 1

    model = {
        "id": new_id,
        "name_ru": name_ru.strip(),
        "hashtags": hashtags.strip(),
        "cover_url": cover_url,
        "media": []
    }

    app_data["models"].append(model)
    save_data(app_data)

    return {"success": True, "id": new_id, "message": "Модель добавлена"}

@app.get("/api/models")
async def get_models(page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200), search: str = Query(None)):
    items = app_data["models"]
    if search:
        s = search.lower()
        items = [m for m in items if s in str(m.get("name_ru", "")).lower()]
    total = len(items)
    start = (page - 1) * limit
    return {
        "items": items[start:start + limit],
        "total": total,
        "page": page
    }

@app.delete("/api/models/{model_id}")
async def delete_model(model_id: int, admin_data: dict = Depends(get_current_admin)):
    app_data["models"] = [m for m in app_data["models"] if m["id"] != model_id]
    save_data(app_data)
    return {"success": True}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
