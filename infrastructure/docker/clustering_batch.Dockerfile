FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY src/clustering_batch_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/clustering_batch_service/ src/clustering_batch_service/
COPY shared/ shared/
COPY config/ config/
COPY data_lake/ data_lake/

CMD ["uvicorn", "src.clustering_batch_service.main:app", "--host", "0.0.0.0", "--port", "8002"]
