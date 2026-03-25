# ──────────────────────────────────────────────────────────────
# Stage 1: Build the React Frontend
# ──────────────────────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund

COPY frontend/ ./
RUN npm run build

# ──────────────────────────────────────────────────────────────
# Stage 2: Python + FastAPI + nginx + Playwright
# ──────────────────────────────────────────────────────────────
FROM python:3.12-slim

# Prevent python from writing pyc files and keep stdout unbuffered
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies (including xvfb for virtual display)
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    supervisor \
    curl \
    wget \
    gnupg \
    ca-certificates \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Set Playwright browser path environment variable
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install Python dependencies first (layer caching)
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers and all system dependencies, then clean up
RUN playwright install chromium \
    && playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# Copy backend source code
COPY backend/ ./

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf
RUN rm -f /etc/nginx/sites-enabled/default

# Copy built React frontend from Stage 1
COPY --from=frontend-builder /app/frontend/dist /usr/share/nginx/html/

# Copy supervisord config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Create required directories for persistence and logs
RUN mkdir -p static/screenshots /var/log/supervisor downloads/landregistry chrome_profile/landregistry output/sessions/results

# Expose ports
EXPOSE 3412 7887

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
