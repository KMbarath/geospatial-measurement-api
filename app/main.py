"""FastAPI application factory."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.files import router as files_router
from app.config import Settings, get_settings
from app.database import Base, make_engine, make_session_factory
from app import models  # noqa: F401  (register tables)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

DESCRIPTION = """
Upload a **Shapefile (.zip)** or **KML** and get per-feature geometry, CRS, attributes and
**area / length measurements** computed in a suitable *projected* CRS (never in degrees).
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Path(settings.storage_dir).mkdir(parents=True, exist_ok=True)
        if settings.database_url.startswith("sqlite:///") and ":memory:" not in settings.database_url:
            Path(settings.database_url.replace("sqlite:///", "", 1)).parent.mkdir(parents=True, exist_ok=True)
        engine = make_engine(settings.database_url)
        Base.metadata.create_all(engine)
        app.state.engine = engine
        app.state.session_factory = make_session_factory(engine)
        yield
        engine.dispose()

    app = FastAPI(title="Geospatial File Measurement API", version="1.0.0",
                  description=DESCRIPTION, lifespan=lifespan)
    app.state.settings = settings
    app.include_router(files_router)

    @app.get("/health", tags=["meta"])
    def health():
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def root():
        return FileResponse(Path(__file__).parent / "static" / "index.html")

    return app


app = create_app()
