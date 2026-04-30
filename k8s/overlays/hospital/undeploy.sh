#!/usr/bin/env bash
# Removes the deployed resources. Does NOT delete PersistentVolumeClaims by default.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

if [ ! -d rendered ]; then
  echo "ERROR: 'rendered/' not found. Run ./deploy.sh first to generate manifests."
  exit 1
fi

set -a
# shellcheck disable=SC1091
source ./config.env
set +a

read -r -p "Delete all clinical-annotation resources in namespace '${NAMESPACE}'? PVCs are kept by default. [y/N] " confirm
if [[ ! "${confirm}" =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 0
fi

kubectl delete -k rendered/ --ignore-not-found=true

echo
read -r -p "Also delete PersistentVolumeClaims (this WILL destroy session data)? [y/N] " confirm_pvc
if [[ "${confirm_pvc}" =~ ^[Yy]$ ]]; then
  kubectl -n "${NAMESPACE}" delete pvc \
    annotation-sessions annotation-faiss annotation-presets annotation-hf-cache pipeline-results \
    --ignore-not-found=true
fi

echo "Done."
