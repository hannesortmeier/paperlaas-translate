#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-paperlaas-translate:latest}"
CONTAINER_NAME="${CONTAINER_NAME:-paperlaas-translate}"
#DOCKER_NETWORK="${DOCKER_NETWORK:-paperless_paperless}"
DOCKER_NETWORK="${DOCKER_NETWORK:-paperlaas-translate_default}"
ENV_FILE="${ENV_FILE:-.env}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Env file not found: ${ENV_FILE}" >&2
  exit 1
fi

docker build -t "${IMAGE_NAME}" .
docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
docker run -d \
  --name "${CONTAINER_NAME}" \
  --restart unless-stopped \
  --network "${DOCKER_NETWORK}" \
  --env-file "${ENV_FILE}" \
  "${IMAGE_NAME}"
