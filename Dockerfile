# ──────────────────────────────────────────────────────────────
# Stage 1: Build the React Frontend
# ──────────────────────────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend

# Install dependencies
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund

# Build production bundle
COPY frontend/ ./
RUN npm run build

# ──────────────────────────────────────────────────────────────
# Stage 2: Python + FastAPI + nginx — single container
# ──────────────────────────────────────────────────────────────
FROM python:3.12-slim

# Install nginx, supervisor, and Playwright system deps in one layer
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx \
    supervisor \
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
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright's Chromium browser and its dependencies
RUN playwright install chromium --with-deps

# Copy backend source code
COPY backend/ ./

# Copy the nginx config (listens on port 3412)
COPY nginx.conf /etc/nginx/conf.d/default.conf
# Disable the default nginx site
RUN rm -f /etc/nginx/sites-enabled/default

# Copy the built React frontend into nginx's serve directory
COPY --from=frontend-builder /app/frontend/dist /usr/share/nginx/html/

# Copy supervisord config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Ensure directories exist
RUN mkdir -p static/screenshots /var/log/supervisor

# Expose ports:
#   3412 → nginx (React frontend + /api proxy)
#   7887 → uvicorn (FastAPI backend)
EXPOSE 3412 7887

CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
