FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias del sistema necesarias
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements primero para aprovechar caché de capas
COPY src/anomaly_detector_api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código
COPY src/anomaly_detector_api/ src/anomaly_detector_api/
COPY shared/ shared/
COPY config/ config/
COPY data_lake/ data_lake/

# Migraciones de base de datos (Alembic)
COPY alembic.ini alembic.ini
COPY alembic/ alembic/

# Scripts operativos (registro de modelo en MLflow, etc.)
COPY scripts/ scripts/

# Comando por defecto
CMD ["uvicorn", "src.anomaly_detector_api.main:app", "--host", "0.0.0.0", "--port", "8001"]
