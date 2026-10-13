from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from src.services.reviews_service import ReviewsService
from src.db_connections.database import get_db_async
from src.services.login_service import LoginService
from src.data_models.users_model import Users
from src.schemas.reviews_schema import CreateReviewSchema, ReviewResponseSchema

router = APIRouter(prefix="/api", tags=["Reviews"])

get_current_active_user = LoginService.get_current_active_user


def reviews_service() -> ReviewsService:
    return ReviewsService()


@router.post("/reviews")
async def create_review(
    payload: CreateReviewSchema,
    db: AsyncSession = Depends(get_db_async),
    service: ReviewsService = Depends(reviews_service),
    user: Users = Depends(get_current_active_user),
):
    """Rate the other party of a delivered order (overall plus quality, communication, reliability, quantity)."""
    return await service.create_review(payload, user.id, db)


@router.get("/reviews/pending")
async def get_pending_reviews(
    db: AsyncSession = Depends(get_db_async),
    service: ReviewsService = Depends(reviews_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.get_pending_reviews(user.id, db)


@router.post("/reviews/{review_id}/response")
async def respond_to_review(
    review_id: int,
    payload: ReviewResponseSchema,
    db: AsyncSession = Depends(get_db_async),
    service: ReviewsService = Depends(reviews_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.respond(review_id, user.id, payload.response, db)


@router.get("/reviews/user/{user_id}")
async def get_user_reviews(
    user_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db_async),
    service: ReviewsService = Depends(reviews_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.get_user_reviews(user_id, db, page, page_size)


@router.get("/reviews/user/{user_id}/summary")
async def get_rating_summary(
    user_id: int,
    db: AsyncSession = Depends(get_db_async),
    service: ReviewsService = Depends(reviews_service),
    user: Users = Depends(get_current_active_user),
):
    return await service.get_rating_summary(user_id, db)
