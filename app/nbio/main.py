from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routes import devices, events, growth, health, pages, settings, stream, sw

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="NBIO Tracker", lifespan=lifespan)

# sw router MUST be included before the StaticFiles mount — it owns
# /static/sw.js so the template substitution runs (issue #23).
app.include_router(sw.router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(health.router)
app.include_router(pages.router)
app.include_router(events.router)
app.include_router(devices.router)
app.include_router(growth.router)
app.include_router(settings.api_router)
app.include_router(settings.page_router)
app.include_router(stream.router)
