from fastapi import APIRouter

from app.api.v1.analyst import router as analyst_router
from app.api.v1.announcement import router as announcement_router
from app.api.v1.auth import router as auth_router
from app.api.v1.customer_service import router as customer_service_router
from app.api.v1.dingtalk import router as dingtalk_router
from app.api.v1.ecommerce import router as ecommerce_router
from app.api.v1.milvus import router as milvus_router
from app.api.v1.orchestrator import router as orchestrator_router
from app.api.v1.products import router as products_router
from app.api.v1.qweather import router as qweather_router

router = APIRouter(prefix="/v1")


@router.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """存活探针，用于快速验证服务是否正常启动。"""
    return {"status": "ok"}


router.include_router(auth_router)
router.include_router(analyst_router)
router.include_router(announcement_router)
router.include_router(customer_service_router)
router.include_router(dingtalk_router)
router.include_router(ecommerce_router)
router.include_router(milvus_router)
router.include_router(orchestrator_router)
router.include_router(products_router)
router.include_router(qweather_router)
