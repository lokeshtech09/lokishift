"""API routers."""

from app.routers.connections import router as connections_router
from app.routers.health import router as health_router
from app.routers.profiles import router as profiles_router
from app.routers.tasks import router as tasks_router

__all__ = ["connections_router", "health_router", "profiles_router", "tasks_router"]
