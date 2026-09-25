# Stage 1: Build Frontend React UI
FROM node:20-alpine AS frontend-builder
WORKDIR /build
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Stage 2: Production Python Backend
FROM python:3.12-slim
WORKDIR /app

# Install system audio dependencies (ffmpeg, libsndfile) and Unicode fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code and compiled frontend
COPY backend/ /app/backend/
COPY --from=frontend-builder /build/dist /app/frontend/dist/

ENV PYTHONPATH=/app/backend
ENV OFFLINE_STRICT=true
ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000
CMD ["python", "backend/run_server.py"]
