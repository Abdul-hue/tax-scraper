from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.urls import api_router
import os

app = FastAPI(title="Scraper API")

# Ensure static directory exists for screenshots
os.makedirs("static/screenshots", exist_ok=True)

# Mount screenshots folder (served at /static/screenshots/<filename>)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Include all API routes
app.include_router(api_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=7887, reload=False)
