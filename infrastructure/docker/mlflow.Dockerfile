FROM python:3.12-slim

RUN pip install --no-cache-dir mlflow

# Exponer el puerto por defecto de MLflow
EXPOSE 5000

# El host 0.0.0.0 permite que otros contenedores lo alcancen
CMD ["mlflow", "server", "--host", "0.0.0.0", "--port", "5000"]
