import asyncio
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from src.helpers.logging_config import get_logger
import src.data_models.registry  # noqa: F401  (registers every model)
from src.core.observability import ApiVersionMiddleware, RequestContextMiddleware, install_error_handlers
from src.core.rate_limit import RateLimitMiddleware
from src.core.realtime import start_pubsub, stop_pubsub
from src.core.scheduler import scheduler_loop, scheduler_enabled
from src.db_connections.mongo_conn import close_mongo_connection
from src.db_connections.database import dispose_engines
from src.routers.login_router import router as login_router
from src.routers.miscellaneous_data_router import router as misc_data_router
from src.routers.users_router import router as users_router
from src.routers.profiles_router import router as profiles_router
from src.routers.files_router import router as files_router
from src.routers.model_router import router as model_router
from src.routers.catalog_router import router as catalog_router
from src.routers.fertilizers_router import router as fertilizer_router
from src.routers.crops_router import router as crops_router
from src.routers.soil_router import router as soil_router
from src.routers.listings_router import router as listings_router
from src.routers.farmer_inventory_router import router as farmer_inventory_router
from src.routers.locations_router import router as location_router
from src.routers.market_router import router as market_router
from src.routers.negotiations_router import router as negotiations_router
from src.routers.orders_router import router as orders_router
from src.routers.payment_router import router as payment_router
from src.routers.payments_history_router import router as payments_history_router
from src.routers.notifications_router import router as notifications_router
from src.routers.inbox_router import router as inbox_router
from src.routers.reviews_router import router as reviews_router
from src.routers.buy_requests_router import router as buy_requests_router
from src.routers.vendor_tools_router import router as vendor_tools_router
from src.routers.expenses_router import router as expenses_router
from src.routers.insights_router import router as insights_router
from src.routers.disputes_router import router as disputes_router
from src.routers.planning_router import router as planning_router
from src.routers.assistant_router import router as assistant_router
from src.routers.support_router import router as support_router
from src.routers.admin_router import router as admin_router
from src.routers.system_router import router as system_router


HOST = "0.0.0.0"
PORT = int(os.getenv("BACKEND_PORT", "8000"))
API_DOCS_ENABLED = os.getenv("API_DOCS_ENABLED", "true").lower() != "false"
ALLOW_ORIGINS = [o.strip() for o in os.getenv(
    "CORS_ALLOW_ORIGINS", "http://localhost,http://127.0.0.1,http://localhost:3000"
).split(",") if o.strip()]
logger = get_logger(__name__)
logger.info("Logger loaded")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Smart-Agri-Tech API is starting up...")
    stop = asyncio.Event()
    task = asyncio.create_task(scheduler_loop(stop)) if scheduler_enabled() else None
    await start_pubsub()
    yield
    logger.info("Shutting down Smart-Agri-Tech API...")
    stop.set()
    if task:
        await task
    await stop_pubsub()
    await close_mongo_connection()
    await dispose_engines()


smart_agri_tech_app = FastAPI(
    title="Smart-Agri-Tech API",
    description=(
        "Negotiation-first marketplace connecting farmers and vendors. Every endpoint under /api is also "
        "available under /api/v1. Errors use {detail, error: {code, status, message, details, request_id}}."
    ),
    version="2.0.0",
    # Interactive docs can be switched off in production with API_DOCS_ENABLED=false.
    docs_url="/docs" if API_DOCS_ENABLED else None,
    redoc_url="/redoc" if API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if API_DOCS_ENABLED else None,
    lifespan=lifespan,
)

for router in (
    login_router, misc_data_router, users_router, profiles_router, files_router, model_router, catalog_router,
    fertilizer_router, crops_router, soil_router, listings_router, farmer_inventory_router, location_router,
    market_router, negotiations_router, orders_router, payment_router, payments_history_router,
    notifications_router, inbox_router, reviews_router, buy_requests_router, vendor_tools_router,
    expenses_router, insights_router, disputes_router, planning_router, assistant_router, support_router,
    admin_router, system_router,
):
    smart_agri_tech_app.include_router(router)

install_error_handlers(smart_agri_tech_app)
smart_agri_tech_app.add_middleware(RateLimitMiddleware)
smart_agri_tech_app.add_middleware(RequestContextMiddleware)
smart_agri_tech_app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)
smart_agri_tech_app.add_middleware(ApiVersionMiddleware)


@smart_agri_tech_app.get("/", tags=["Health Check"])
async def home():
    """
    Health check endpoint to ensure the backend is running.
    """
    return {
        "message": "Smart-Agri-Tech backend application is successfully running.",
        "status": "success"
    }


if __name__ == "__main__":
    # Development server with auto-reload (production uses gunicorn: ./entrypoint.sh serve).
    uvicorn.run("main:smart_agri_tech_app", host=HOST, port=PORT, reload=True, reload_dirs=["src"])
