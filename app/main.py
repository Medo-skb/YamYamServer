from fastapi import FastAPI

from app.api.routers import gifticons, health, point_payments, recommendations, stamps


def create_app() -> FastAPI:
    application = FastAPI()
    application.include_router(health.router)
    application.include_router(recommendations.router)
    application.include_router(gifticons.router)
    application.include_router(point_payments.router)
    application.include_router(stamps.router)
    return application


app = create_app()
