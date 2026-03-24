from fastapi import APIRouter

router = APIRouter()

@router.get("/")
async def get_core_info():
    return {"module": "core", "status": "active"}

@router.get("/health")
async def health_check():
    return {"status": "ok"}
