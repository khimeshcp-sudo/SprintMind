FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev git \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY deploy ./deploy

RUN mkdir -p /app/data/uploads /app/data/workspace \
    && git config --global --add safe.directory /app/magento \
    && git config --global user.name "SprintMind Bot" \
    && git config --global user.email "sprintmind-bot@users.noreply.github.com"

ENV MAGENTO_PROJECT_PATH=/app/magento
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
