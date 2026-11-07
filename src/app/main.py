import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.app.core.config import get_settings
from src.app.api.routes.instruction import router as instruction_router
from src.app.api.routes.tasks import router as tasks_router
from src.app.api.routes.transcribe import router as transcribe_router


def create_app() -> FastAPI:
    settings = get_settings()
    origins = [origin for origin in settings.allowed_origins if origin != "*"]
    codespace_name = os.getenv("CODESPACE_NAME")
    forwarding_domain = os.getenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN")
    if codespace_name and forwarding_domain:
        origins.append(f"https://{codespace_name}-5173.{forwarding_domain}")
    app = FastAPI(
        title="Voice Command Transcription API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(tasks_router)
    app.include_router(instruction_router)
    app.include_router(transcribe_router)
    return app


app = create_app()
