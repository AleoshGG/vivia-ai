FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY src/llm_local_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/llm_local_service/ src/llm_local_service/
COPY shared/ shared/
COPY config/ config/

CMD ["uvicorn", "src.llm_local_service.main:app", "--host", "0.0.0.0", "--port", "8003"]
