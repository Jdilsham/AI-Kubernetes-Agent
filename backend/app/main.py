from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api import health, routes
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.kubernetes.kubectl import ensure_in_cluster_kubeconfig
from app.services import store

setup_logging()
settings = get_settings()



@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_in_cluster_kubeconfig()
    store.fail_running()
    if settings.auth_mode == "password" and not settings.admin_password:
        logger.warning("AUTH_MODE=password but ADMIN_PASSWORD is empty: nobody can log in")
    logger.info("{} started (auth={})", settings.service_name, settings.auth_mode)
    yield


app = FastAPI(title="AI Kubernetes Agent", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(routes.router)
app.include_router(routes.protected)
