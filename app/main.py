from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes.campaigns import router as campaigns_router
from app.api.routes.dashboard import router as dashboard_router


def create_app() -> FastAPI:
    app = FastAPI(title="Marketing Analytics API", version="1.0.0")

    # Versioned API (v1)
    app.include_router(campaigns_router, prefix="/v1")
    app.include_router(dashboard_router)

    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    @app.get("/")
    def root() -> dict[str, str]:
        return {"message": "Marketing Analytics API running", "versions": ["v1"]}

    return app


app = create_app()