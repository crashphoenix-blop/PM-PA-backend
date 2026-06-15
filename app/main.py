from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.ingestion.images import get_uploads_dir
from app.routers import ai, analytics, auth, categories, favorites, gifts, ingestion, users


def create_app() -> FastAPI:
    """
    Application factory.

    Используем фабрику, чтобы упростить конфигурацию
    и тестирование приложения.
    """
    app = FastAPI(
        title="SURPRISE API",
        description="Backend for SURPRISE gift picking app",
        version="0.1.0",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    app.include_router(ai.router, prefix="/ai", tags=["ai"])
    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(users.router, prefix="/users", tags=["users"])
    app.include_router(categories.router, prefix="/categories", tags=["categories"])
    app.include_router(gifts.router, prefix="/gifts", tags=["gifts"])
    app.include_router(favorites.router, prefix="/favorites", tags=["favorites"])
    app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
    app.include_router(ingestion.router, prefix="/admin/ingestion", tags=["ingestion"])

    uploads_dir = get_uploads_dir()
    app.mount("/media", StaticFiles(directory=str(uploads_dir)), name="media")

    @app.get("/", tags=["health"])
    async def root_health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
