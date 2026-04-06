from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.urls import api_router
import os
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

app = FastAPI(title="Scraper API")

from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://192.168.80.52:2310",
        "http://192.168.80.52:2510"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Ensure static directory exists for screenshots and PDFs
os.makedirs("static/screenshots", exist_ok=True)
os.makedirs("static/pdfs", exist_ok=True)

# Mount static folder (served at /static/<path>)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include all API routes
app.include_router(api_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
