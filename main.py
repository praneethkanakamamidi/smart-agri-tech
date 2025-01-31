from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
import uvicorn
import os
from src.helpers.logging_config import get_logger

from src.routers.login_router import router as login_router
from src.routers.miscellaneous_data_router import router as misc_data_router
from src.routers.users_router import router as users_router

HOST = "0.0.0.0"
PORT = os.getenv("BACKEND_PORT")
ALLOW_ORIGINS = ["http://localhost", "http://127.0.0.1"]
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

if __name__ == "__main__":
    uvicorn.run(
        smart_agri_tech_app, 
        host=HOST, 
        port=PORT,
        reload=True,
        reload_dirs=["/app/src"]
    )
          