from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .config import APP_VERSION, FRONTEND_DIR
from .api.devices import router as devices_router
from .api.resources import router as resources_router
from .api.system import router as system_router
from .db import SessionLocal
from .services.catalogs import seed_defaults

@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_catalogs_on_startup()
    yield

app = FastAPI(title='РИС — Реестр ИТ-инфраструктуры', version=APP_VERSION, lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
app.include_router(system_router)
app.include_router(devices_router)
app.include_router(resources_router)

def seed_catalogs_on_startup():
    session = SessionLocal()
    try:
        seed_defaults(session)
    finally:
        session.close()

static_dir = FRONTEND_DIR / 'static'
if static_dir.is_dir():
    app.mount('/static', StaticFiles(directory=static_dir), name='static')
