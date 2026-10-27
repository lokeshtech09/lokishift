"""LokiShift API entry point."""

import logging

from app.redact import install_log_redaction

# Before anything else logs: no API key may ever reach a log line.
install_log_redaction()

from collections.abc import AsyncIterator  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from app import __version__  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import DatabaseBusyError, db  # noqa: E402
from app.routers import connections_router, health_router, profiles_router, tasks_router  # noqa: E402
from app.services import worker  # noqa: E402

logger = logging.getLogger(__name__)


def _configure_application_logging() -> None:
    numeric_level = getattr(logging, settings.log_level, logging.INFO)
    logging.getLogger("app").setLevel(numeric_level)


_configure_application_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    await worker.start()
    yield
    try:
        await worker.stop()
    except Exception:
        logger.exception("Error stopping worker")
    try:
        await db.close()
    except Exception:
        logger.exception("Error closing database")


app = FastAPI(
    title="LokiShift API",
    description="Match resume versions to job descriptions and tailor them in the background.",
    version=__version__,
    lifespan=lifespan,
)


@app.exception_handler(DatabaseBusyError)
async def database_busy_handler(request: Request, error: DatabaseBusyError) -> JSONResponse:
    logger.warning("Database write contention for %s", request.url.path, exc_info=error)
    return JSONResponse(
        status_code=503,
        content={"detail": "Database is busy. Please retry shortly."},
        headers={"Retry-After": "1"},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.effective_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix="/api/v1")
app.include_router(connections_router, prefix="/api/v1")
app.include_router(profiles_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": "LokiShift API", "version": __version__, "docs": "/docs"}


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=settings.reload)


if __name__ == "__main__":
    main()
