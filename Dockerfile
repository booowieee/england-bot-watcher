# ==============================================================================
# Production Dockerfile for SWS Telegram Monitor Bot
# Multi-stage lightweight build with Playwright Chromium headless engine
# ==============================================================================

FROM python:3.12-slim-bookworm

# Установка системных зависимостей для Playwright Chromium
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    curl \
    gnupg \
    ca-certificates \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    fonts-liberation \
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Установка Python зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Установка только Chromium браузера для Playwright
RUN playwright install chromium

# Копирование исходного кода проекта
COPY src/ ./src/
COPY README.md .

# Создание директории для персистентных данных
RUN mkdir -p /app/data/screenshots /app/logs

# Создание непривилегированного пользователя для безопасности
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app /ms-playwright

USER appuser

# Запуск монитора
CMD ["python", "-m", "src.main"]
