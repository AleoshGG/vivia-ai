FROM python:3.12-slim

# psycopg2 (backend-store Postgres) + gcsfs (artifact-store GCS)
RUN pip install --no-cache-dir mlflow psycopg2-binary gcsfs google-cloud-storage

# Exponer el puerto por defecto de MLflow
EXPOSE 5000

# El backend-store (Postgres) habilita el Model Registry con stages.
# Los artefactos van a GCS (MLFLOW_ARTIFACT_ROOT). El host 0.0.0.0 permite que
# otros contenedores lo alcancen.
CMD ["sh", "-c", "mlflow server --host 0.0.0.0 --port 5000 \
    --backend-store-uri \"$MLFLOW_BACKEND_STORE_URI\" \
    --artifacts-destination \"$MLFLOW_ARTIFACT_ROOT\""]
