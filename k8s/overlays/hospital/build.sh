#!/usr/bin/env bash
# Clinical Annotation Platform: Hospital Image Build & Push Script
#
# Reads config.env, builds the four container images (with the correct
# NEXT_PUBLIC_API_URL baked into the frontend), and pushes them to your registry.
#
# Run from this directory: ./build.sh
# Run AFTER editing config.env, BEFORE ./deploy.sh.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "${SCRIPT_DIR}"

# ----- Pre-flight -----
command -v docker >/dev/null 2>&1 || { echo "ERROR: docker not found in PATH"; exit 1; }

if [ ! -f config.env ]; then
  echo "ERROR: config.env not found in $(pwd)"
  exit 1
fi

# Sanity-check that the source tree is reachable
for d in backend frontend pipeline/api pipeline/status_web; do
  if [ ! -d "${REPO_ROOT}/${d}" ]; then
    echo "ERROR: source directory ${REPO_ROOT}/${d} not found"
    echo "       This script must run from inside the project repository."
    exit 1
  fi
done

# ----- Load and validate config -----
set -a
# shellcheck disable=SC1091
source ./config.env
set +a

REQUIRED_VARS=(REGISTRY IMAGE_TAG DOMAIN)
for var in "${REQUIRED_VARS[@]}"; do
  if [ -z "${!var:-}" ]; then
    echo "ERROR: Required variable '${var}' is empty in config.env"
    exit 1
  fi
done

# Choose http vs https for the API URL baked into the frontend image,
# matching what the Ingress will actually serve.
if [ -n "${TLS_SECRET_NAME:-}" ]; then
  API_URL_SCHEME="https"
else
  API_URL_SCHEME="http"
fi
FRONTEND_API_URL="${API_URL_SCHEME}://${DOMAIN}"

DEPLOY_PIPELINE_SERVICES="${DEPLOY_PIPELINE_SERVICES:-false}"

# ----- Summary & confirmation -----
echo "==============================================="
echo "Build & push plan:"
echo "  Registry:         ${REGISTRY}"
echo "  Tag:              ${IMAGE_TAG}"
echo "  Frontend API URL: ${FRONTEND_API_URL}  (baked into the image)"
echo "  Pipeline images:  ${DEPLOY_PIPELINE_SERVICES}"
echo "  Source root:      ${REPO_ROOT}"
echo "==============================================="
echo
echo "Images to build:"
echo "  ${REGISTRY}/annotation-api:${IMAGE_TAG}"
echo "  ${REGISTRY}/annotation-web:${IMAGE_TAG}"
if [ "${DEPLOY_PIPELINE_SERVICES}" = "true" ]; then
  echo "  ${REGISTRY}/pipeline-api:${IMAGE_TAG}"
  echo "  ${REGISTRY}/pipeline-dashboard:${IMAGE_TAG}"
fi
echo
read -r -p "Proceed with build and push? Make sure you are 'docker login'd to ${REGISTRY%%/*}. [y/N] " confirm
if [[ ! "${confirm}" =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 0
fi

# ----- Build & push -----
build_and_push() {
  local image="$1"
  local context="$2"
  shift 2
  local extra_args=("$@")

  echo
  echo "------ Building ${image} ------"
  docker build "${extra_args[@]}" -t "${image}" "${context}"
  echo "------ Pushing ${image} ------"
  docker push "${image}"
}

build_and_push \
  "${REGISTRY}/annotation-api:${IMAGE_TAG}" \
  "${REPO_ROOT}/backend"

build_and_push \
  "${REGISTRY}/annotation-web:${IMAGE_TAG}" \
  "${REPO_ROOT}/frontend" \
  --build-arg "NEXT_PUBLIC_API_URL=${FRONTEND_API_URL}"

if [ "${DEPLOY_PIPELINE_SERVICES}" = "true" ]; then
  build_and_push \
    "${REGISTRY}/pipeline-api:${IMAGE_TAG}" \
    "${REPO_ROOT}/pipeline/api"

  build_and_push \
    "${REGISTRY}/pipeline-dashboard:${IMAGE_TAG}" \
    "${REPO_ROOT}/pipeline/status_web"
fi

echo
echo "==============================================="
echo "All images built and pushed."
echo "Next step: ./deploy.sh"
echo "==============================================="
