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

FAVICON_CACHE_CONTROL = 'public, max-age=86400'

@router.get('/favicon.ico', include_in_schema=False)
def favicon():
    """Иконка вкладки браузера (frontend-vue/public/favicon.ico, копируется в dist при сборке).

    Браузер просит её сам по /favicon.ico, даже когда в index.html нет <link rel="icon">, а за пределами /api/ запросы не
    проходят проверку аутентификации — поэтому иконка видна и на экране входа. Тип задан явно (а не угадывается по
    расширению платформой), кэш — сутки: файл меняется только с новой сборкой."""
    icon = FRONTEND_DIR / 'favicon.ico'
    if icon.is_file():
        return FileResponse(icon, media_type='image/x-icon', headers={'Cache-Control': FAVICON_CACHE_CONTROL})
    raise HTTPException(404, 'favicon.ico не найден')
