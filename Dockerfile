FROM node:22-alpine AS frontend-build
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS app
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ ./backend/
COPY dataset/labels/ ./dataset/labels/
COPY artifacts/routes.geojson ./artifacts/routes.geojson
COPY artifacts/stops.json ./artifacts/stops.json
COPY artifacts/external/ ./artifacts/external/
COPY submission.csv ./submission.csv
COPY --from=frontend-build /ui/dist ./frontend/dist
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
