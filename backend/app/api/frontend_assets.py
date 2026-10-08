"""Статические файлы интерфейса вне /assets: спрайт иконок и favicon.

Сама страница интерфейса (`/` и SPA-фоллбэк) отдаётся из main.spa_fallback.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import FRONTEND_DIR

router = APIRouter()

@router.get('/icons.svg', include_in_schema=False)
def frontend_icons():
    """Спрайт иконок Vue-интерфейса (frontend-vue/public/icons.svg, копируется в dist при
    сборке) — компоненты ссылаются на него абсолютным путём '<use href="/icons.svg#i-...">'."""
    icons = FRONTEND_DIR / 'icons.svg'
    if icons.is_file(): return FileResponse(icons, media_type='image/svg+xml')
    raise HTTPException(404, 'icons.svg не найден')

@router.get('/favicon.ico', include_in_schema=False)
def favicon():
    icon = FRONTEND_DIR / 'favicon.ico'
    if icon.is_file(): return FileResponse(icon)
    raise HTTPException(404, 'favicon.ico не найден')
