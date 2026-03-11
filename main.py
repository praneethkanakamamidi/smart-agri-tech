from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
import uvicorn
import os
from src.helpers.logging_config import get_logger
from contextlib import asynccontextmanager
from src.routers.login_router import router as login_router
from src.routers.miscellaneous_data_router import router as misc_data_router
from src.routers.users_router import router as users_router
from src.routers.model_router import router as model_router
from src.routers.fertilizers_router import router as fertilizer_router
from src.routers.crops_router import router as crops_router
from src.routers.soil_router import router as soil_router
from src.routers.farmer_inventory_router import router as farmer_inventory_router
from src.routers.locations_router import router as location_router
from src.routers.market_router import router as market_router
from src.routers.market_offers_router import router as market_offers_router
from src.routers.orders_router import router as orders_router
from src.routers.payment_router import router as payment_router
from src.routers.payments_history_router import router as payments_history_router
from src.db_connections.mongo_conn import close_mongo_connection



HOST = "0.0.0.0"
PORT = os.getenv("BACKEND_PORT")
PORT = int(PORT)
ALLOW_ORIGINS = [
    "http://localhost",
    "http://127.0.0.1",
    "http://localhost:3000"
]
logger = get_logger(__name__)
logger.info("Logger loaded")

smart_agri_tech_app = FastAPI(
    title="Smart-Agri-Tech API",
    description="Backend service for Smart-Agri-Tech application.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)
 
smart_agri_tech_app.include_router(login_router)
smart_agri_tech_app.include_router(misc_data_router)
smart_agri_tech_app.include_router(users_router)
smart_agri_tech_app.include_router(model_router)
smart_agri_tech_app.include_router(fertilizer_router)
smart_agri_tech_app.include_router(crops_router)
smart_agri_tech_app.include_router(soil_router)
smart_agri_tech_app.include_router(farmer_inventory_router)
smart_agri_tech_app.include_router(location_router)
smart_agri_tech_app.include_router(market_router)
smart_agri_tech_app.include_router(market_offers_router)
smart_agri_tech_app.include_router(orders_router)
smart_agri_tech_app.include_router(payment_router)
smart_agri_tech_app.include_router(payments_history_router)


 
smart_agri_tech_app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
 
@smart_agri_tech_app.get("/", tags=["Health Check"])
async def home():
    """
    Health check endpoint to ensure the backend is running.
    """
    return {
        "message": "Smart-Agri-Tech backend application is successfully running.",
        "status": "success"
    }

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Smart-Agri-Tech API is starting up...")
    yield
    logger.info("Shutting down Smart-Agri-Tech API...")
    await close_mongo_connection()

if __name__ == "__main__":
    uvicorn.run(
        smart_agri_tech_app, 
        host=HOST, 
        port=PORT,
        reload=True, 
        reload_dirs=["/app/src"]
    )
