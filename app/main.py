from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import analytics, auth, categories, favorites, gifts, users


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
    app.include_router(auth.router, prefix="/auth", tags=["auth"])
    app.include_router(users.router, prefix="/users", tags=["users"])
    app.include_router(categories.router, prefix="/categories", tags=["categories"])
    app.include_router(gifts.router, prefix="/gifts", tags=["gifts"])
    app.include_router(favorites.router, prefix="/favorites", tags=["favorites"])
    app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])

    return app


app = create_app()
