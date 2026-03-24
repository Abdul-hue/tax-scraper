from fastapi import APIRouter

router = APIRouter()

@router.get("/login")
async def login():
    return {"message": "Login successful"}

@router.post("/register")
async def register():
    return {"message": "Registration successful"}
