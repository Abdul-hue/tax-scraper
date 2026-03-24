# ──────────────────────────────────────────────────────────────
# PRODUCTION DOCKERFILE: FastAPI + Playwright
# Optimized for Render Deployment
# ──────────────────────────────────────────────────────────────
FROM python:3.12-slim

# Install system dependencies for Playwright and Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libxshmfence1 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=10000

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright's Chromium browser and its system dependencies
RUN playwright install chromium --with-deps

# Copy backend source code
COPY . .

# Ensure directories exist for persistent storage if needed
RUN mkdir -p static/screenshots static/pdfs

# Expose the port Render expects
EXPOSE 10000

# Run the application using uvicorn
CMD uvicorn main:app --host 0.0.0.0 --port $PORT
