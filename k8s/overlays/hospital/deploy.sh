#!/usr/bin/env bash
# Clinical Annotation Platform: Hospital Deployment Script
#
# Reads config.env, renders templates, and applies the manifests to your cluster.
# Run from this directory: ./deploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

# ----- Pre-flight -----
command -v kubectl >/dev/null 2>&1 || { echo "ERROR: kubectl not found in PATH"; exit 1; }
command -v envsubst >/dev/null 2>&1 || { echo "ERROR: envsubst not found (install package 'gettext')"; exit 1; }

if [ ! -f config.env ]; then
  echo "ERROR: config.env not found in $(pwd)"
  exit 1
fi

# ----- Load and validate config -----
set -a
# shellcheck disable=SC1091
source ./config.env
set +a

REQUIRED_VARS=(NAMESPACE REGISTRY IMAGE_TAG VLLM_ENDPOINT VLLM_MODEL_NAME DOMAIN INGRESS_CLASS \
  SESSIONS_STORAGE FAISS_STORAGE PRESETS_STORAGE HF_CACHE_STORAGE PIPELINE_RESULTS_STORAGE \
  API_CPU_REQUEST API_MEMORY_REQUEST API_CPU_LIMIT API_MEMORY_LIMIT)
for var in "${REQUIRED_VARS[@]}"; do
  if [ -z "${!var:-}" ]; then
    echo "ERROR: Required variable '${var}' is empty in config.env"
    exit 1
  fi
done

DEPLOY_PIPELINE_SERVICES="${DEPLOY_PIPELINE_SERVICES:-false}"

# ----- Render templates -----
RENDERED="rendered"
rm -rf "${RENDERED}"
mkdir -p "${RENDERED}/patches"

echo "Rendering templates from config.env..."
envsubst < templates/patches/annotation-api-config.yaml.tpl    > "${RENDERED}/patches/annotation-api-config.yaml"
envsubst < templates/patches/annotation-api-resources.yaml.tpl > "${RENDERED}/patches/annotation-api-resources.yaml"
envsubst < templates/patches/storage-sizes.yaml.tpl            > "${RENDERED}/patches/storage-sizes.yaml"

# ----- Render Ingress (with conditional TLS and pipeline path) -----
INGRESS_TLS_BLOCK=""
if [ -n "${TLS_SECRET_NAME:-}" ]; then
  INGRESS_TLS_BLOCK=$(cat <<EOF
  tls:
    - hosts:
        - ${DOMAIN}
      secretName: ${TLS_SECRET_NAME}
EOF
)
fi

INGRESS_PIPELINE_PATH=""
if [ "${DEPLOY_PIPELINE_SERVICES}" = "true" ]; then
  INGRESS_PIPELINE_PATH=$(cat <<'EOF'
          - path: /pipeline
            pathType: Prefix
            backend:
              service:
                name: pipeline-dashboard
                port:
                  number: 8501
EOF
)
fi

cat > "${RENDERED}/ingress.yaml" <<EOF
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: clinical-annotation-ingress
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "300"
spec:
  ingressClassName: ${INGRESS_CLASS}
${INGRESS_TLS_BLOCK}
  rules:
    - host: ${DOMAIN}
      http:
        paths:
          - path: /api
            pathType: Prefix
            backend:
              service:
                name: annotation-api
                port:
                  number: 8001
          - path: /metrics
            pathType: Prefix
            backend:
              service:
                name: annotation-api
                port:
                  number: 8001
${INGRESS_PIPELINE_PATH}
          - path: /
            pathType: Prefix
            backend:
              service:
                name: annotation-web
                port:
                  number: 3000
EOF

# ----- Optional: storage class patch -----
STORAGE_CLASS_PATCH_BLOCK=""
if [ -n "${STORAGE_CLASS:-}" ]; then
  cat > "${RENDERED}/patches/storage-class.yaml" <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: annotation-sessions
spec:
  storageClassName: ${STORAGE_CLASS}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: annotation-faiss
spec:
  storageClassName: ${STORAGE_CLASS}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: annotation-presets
spec:
  storageClassName: ${STORAGE_CLASS}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: annotation-hf-cache
spec:
  storageClassName: ${STORAGE_CLASS}
EOF
  if [ "${DEPLOY_PIPELINE_SERVICES}" = "true" ]; then
    cat >> "${RENDERED}/patches/storage-class.yaml" <<EOF
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: pipeline-results
spec:
  storageClassName: ${STORAGE_CLASS}
EOF
  fi
  STORAGE_CLASS_PATCH_BLOCK="  - path: patches/storage-class.yaml"
fi

# ----- Optional: pipeline-results storage size patch (only if deploying pipeline) -----
PIPELINE_RESOURCES_PATCH_BLOCK=""
if [ "${DEPLOY_PIPELINE_SERVICES}" = "true" ]; then
  cat > "${RENDERED}/patches/pipeline-storage.yaml" <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: pipeline-results
spec:
  resources:
    requests:
      storage: ${PIPELINE_RESULTS_STORAGE}
EOF
  PIPELINE_RESOURCES_PATCH_BLOCK="  - path: patches/pipeline-storage.yaml"
fi

# ----- Build kustomization.yaml -----
# Note: when DEPLOY_PIPELINE_SERVICES=false, we list only the base resources we want
# (excluding pipeline-* files) instead of patching them out, because Kustomize cannot
# remove resources from a referenced base.
if [ "${DEPLOY_PIPELINE_SERVICES}" = "true" ]; then
  RESOURCES_BLOCK="  - ../../base"
else
  # Reference each non-pipeline base resource individually
  RESOURCES_BLOCK="  - ../../base/namespace.yaml
  - ../../base/annotation-api/configmap.yaml
  - ../../base/annotation-api/pvc.yaml
  - ../../base/annotation-api/deployment.yaml
  - ../../base/annotation-api/service.yaml
  - ../../base/annotation-web/deployment.yaml
  - ../../base/annotation-web/service.yaml"
fi

cat > "${RENDERED}/kustomization.yaml" <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization

namespace: ${NAMESPACE}

resources:
${RESOURCES_BLOCK}
  - ingress.yaml

patches:
  - path: patches/annotation-api-config.yaml
  - path: patches/annotation-api-resources.yaml
  - path: patches/storage-sizes.yaml
${STORAGE_CLASS_PATCH_BLOCK}
${PIPELINE_RESOURCES_PATCH_BLOCK}

images:
  - name: clinical-annotation-api
    newName: ${REGISTRY}/annotation-api
    newTag: "${IMAGE_TAG}"
  - name: clinical-annotation-web
    newName: ${REGISTRY}/annotation-web
    newTag: "${IMAGE_TAG}"
EOF

if [ "${DEPLOY_PIPELINE_SERVICES}" = "true" ]; then
  cat >> "${RENDERED}/kustomization.yaml" <<EOF
  - name: clinical-pipeline-api
    newName: ${REGISTRY}/pipeline-api
    newTag: "${IMAGE_TAG}"
  - name: clinical-pipeline-dashboard
    newName: ${REGISTRY}/pipeline-dashboard
    newTag: "${IMAGE_TAG}"
EOF
fi

# Strip empty patch lines (left behind by unset optional blocks)
sed -i.bak '/^[[:space:]]*$/d' "${RENDERED}/kustomization.yaml"
rm -f "${RENDERED}/kustomization.yaml.bak"

# ----- Preview -----
echo
echo "==============================================="
echo "Rendered manifests written to: ${RENDERED}/"
echo "Showing what kubectl will apply..."
echo "==============================================="
echo
kubectl kustomize "${RENDERED}" || {
  echo
  echo "ERROR: 'kubectl kustomize' failed. Check the rendered files in ${RENDERED}/ for issues."
  exit 1
}

echo
echo "==============================================="
echo "Target namespace: ${NAMESPACE}"
echo "Domain:           ${DOMAIN}"
echo "LLM endpoint:     ${VLLM_ENDPOINT}"
echo "Model:            ${VLLM_MODEL_NAME}"
echo "Pipeline services: ${DEPLOY_PIPELINE_SERVICES}"
echo "==============================================="
read -r -p "Apply these manifests now? [y/N] " confirm
if [[ ! "${confirm}" =~ ^[Yy]$ ]]; then
  echo "Aborted. Rendered manifests remain in ${RENDERED}/ for inspection."
  exit 0
fi

# ----- Apply -----
echo
echo "Creating namespace if missing..."
kubectl get namespace "${NAMESPACE}" >/dev/null 2>&1 || kubectl create namespace "${NAMESPACE}"

echo "Applying manifests..."
kubectl apply -k "${RENDERED}"

echo
echo "==============================================="
echo "Applied. Current pod status:"
echo "==============================================="
kubectl -n "${NAMESPACE}" get pods
echo
echo "Watch rollout:"
echo "  kubectl -n ${NAMESPACE} rollout status deployment/annotation-api"
echo
echo "Application URL: https://${DOMAIN}"
