#!/usr/bin/env bash
#
# Sube los artefactos del modelo (models_registry/) al VPS.
#
# Los modelos NO se versionan en Git ni se hornean en la imagen Docker: son
# artefactos que viven en una carpeta persistente del VPS y se montan como
# volumen en el contenedor (ver compose.yml -> MODELS_REGISTRY_HOST).
#
# Uso:
#   ./infrastructure/cloud_deploy/push_models.sh usuario@mi-vps
#   SSH_KEY=~/.ssh/mi-llave.pem ./push_models.sh ubuntu@mi-vps
#   VPS_PATH=/srv/vivia/models_registry ./push_models.sh usuario@mi-vps
#
# Variables opcionales:
#   SSH_KEY    Ruta a la llave privada (.pem). Si se omite, usa la config SSH por defecto.
#   VPS_PATH   Carpeta destino en el VPS (default: /srv/vivia/models_registry).
#
set -euo pipefail

VPS_HOST="${1:-}"
VPS_PATH="${VPS_PATH:-/srv/vivia/models_registry}"
SSH_KEY="${SSH_KEY:-}"

# Construye las opciones de SSH/rsync según haya o no llave explícita.
SSH_OPTS=()
if [[ -n "${SSH_KEY}" ]]; then
  SSH_OPTS=(-i "${SSH_KEY}")
fi
SSH_CMD=(ssh "${SSH_OPTS[@]}")

# Directorio del repo (la carpeta padre de infrastructure/)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOCAL_DIR="${REPO_ROOT}/models_registry/"

if [[ -z "${VPS_HOST}" ]]; then
  echo "ERROR: falta el host del VPS." >&2
  echo "Uso: $0 usuario@mi-vps" >&2
  exit 1
fi

if [[ ! -d "${LOCAL_DIR}" ]]; then
  echo "ERROR: no existe ${LOCAL_DIR}" >&2
  exit 1
fi

echo "==> Asegurando carpeta destino en el VPS: ${VPS_PATH}"
# /srv suele requerir privilegios: creamos la carpeta con sudo y se la cedemos
# al usuario de conexión para que rsync pueda escribir sin sudo.
REMOTE_USER="${VPS_HOST%@*}"
"${SSH_CMD[@]}" "${VPS_HOST}" \
  "sudo mkdir -p '${VPS_PATH}' && sudo chown -R '${REMOTE_USER}':'${REMOTE_USER}' '${VPS_PATH}'"

echo "==> Sincronizando modelos hacia ${VPS_HOST}:${VPS_PATH}"
# --delete deja el destino idéntico al origen (borra modelos viejos eliminados).
# Excluimos marcadores de Git que no aportan en el VPS.
rsync -avz --progress --delete \
  -e "${SSH_CMD[*]}" \
  --exclude '.gitkeep' \
  --exclude 'README.md' \
  "${LOCAL_DIR}" "${VPS_HOST}:${VPS_PATH}/"

echo "==> Listo. Recuerda en el VPS tener en .env:"
echo "    MODELS_REGISTRY_HOST=${VPS_PATH}"
echo "    y reiniciar el servicio:  docker compose up -d --no-deps anomaly-api"
