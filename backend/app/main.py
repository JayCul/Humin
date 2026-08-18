from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import get_settings

logging.basicConfig(level=logging.INFO)
# On Lambda, the runtime attaches its own handler to the root logger before
# our code ever runs - basicConfig() is a no-op once a handler already
# exists, so it silently doesn't raise the level there even though it works
# fine locally. Setting the level directly always takes effect.
logging.getLogger().setLevel(logging.INFO)

settings = get_settings()

app = FastAPI(
    title="Humin",
    description="Autonomous ad manager - Think (Huginn) / Remember (Muninn) / Learn / Adapt.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/")
def root():
    return {
        "service": "Humin",
        "mode": {"mock_llm": settings.use_mock_llm, "mock_db": settings.use_mock_db},
        "docs": "/docs",
    }
