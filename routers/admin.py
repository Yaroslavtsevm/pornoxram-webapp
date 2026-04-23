from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File
import cloudinary.uploader
from typing import Dict

from ..main import app_data, save_data, validate_init_data, ADMIN_USER_ID  # импортируем из main

router = APIRouter(prefix="/api", tags=["Admin"])

# ===================== ЗАВИСИМОСТЬ АДМИНА =====================
def get_current_admin(init_data: str = Form(alias="init_data")):
    data = validate_init_data(init_data)
    if not data or data.get("user", {}).get("id") != ADMIN_USER_ID:
        raise HTTPException(status_code=403, detail="Доступ запрещён. Вы не администратор.")
    return data


# ===================== ДОБАВЛЕНИЕ МОДЕЛИ =====================
@router.post("/models")
async def add_model(
    name_ru: str = Form(...),
    hashtags: str = Form(""),
    cover: UploadFile = File(...),
    admin_data: Dict = Depends(get_current_admin)
):
    """Добавить новую модель (только для админа)"""
    
    # Загрузка в Cloudinary
    contents = await cover.read()
    result = cloudinary.uploader.upload(
        contents,
        resource_type="image",
        folder="pornoxram",
        use_filename=True,
        unique_filename=True,
        transformation=[{"width": 1200, "crop": "limit"}, {"quality": "auto"}]
    )
    cover_url = result["secure_url"]

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

    return {"success": True, "id": new_id, "message": "Модель успешно добавлена"}


# ===================== УДАЛЕНИЕ МОДЕЛИ =====================
@router.delete("/models/{model_id}")
async def delete_model(model_id: int, admin_data: Dict = Depends(get_current_admin)):
    """Удалить модель (только для админа)"""
    original_len = len(app_data["models"])
    app_data["models"] = [m for m in app_data["models"] if m["id"] != model_id]
    
    if len(app_data["models"]) == original_len:
        raise HTTPException(status_code=404, detail="Модель не найдена")
    
    save_data(app_data)
    return {"success": True, "message": f"Модель {model_id} удалена"}


# Опционально: получить информацию о текущем админе
@router.get("/admin/me")
async def admin_me(admin_data: Dict = Depends(get_current_admin)):
    return {"status": "ok", "user": admin_data.get("user")}
