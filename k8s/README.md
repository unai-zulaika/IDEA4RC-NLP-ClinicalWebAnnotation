# Kubernetes Deployment

Three overlays are provided. Pick the one that matches your situation.

## Layout

```
k8s/
  base/                Generic manifests (Deployments, Services, ConfigMap, PVCs)
  overlays/
    dev/               Local development (port-forward, reduced resources)
    prod/              Generic production (Ingress, image overrides, CORS)
    hospital/          Self-contained hospital deployment package
```

## `overlays/dev` -- local development

Reduced resources, no Ingress (use `kubectl port-forward`).

```bash
kubectl apply -k k8s/overlays/dev/
kubectl -n clinical-annotation port-forward svc/dev-annotation-web 3000:3000 &
kubectl -n clinical-annotation port-forward svc/dev-annotation-api 8001:8001 &
```

Edit `k8s/overlays/dev/patches/annotation-api-llm-config.yaml` to point at your dev LLM endpoint.

## `overlays/prod` -- generic production

Includes Ingress with path-based routing, CORS configuration, production resource limits, and image overrides for a registry.

```bash
# Build and push images (set your registry)
export REGISTRY=your-registry.example.com/clinical
export TAG=$(git rev-parse --short HEAD)

docker build -t ${REGISTRY}/annotation-api:${TAG} ./backend
docker build --build-arg NEXT_PUBLIC_API_URL=https://clinical.example.com \
  -t ${REGISTRY}/annotation-web:${TAG} ./frontend
docker build -t ${REGISTRY}/pipeline-api:${TAG} ./pipeline/api
docker build -t ${REGISTRY}/pipeline-dashboard:${TAG} ./pipeline/status_web

docker push ${REGISTRY}/annotation-api:${TAG}
docker push ${REGISTRY}/annotation-web:${TAG}
docker push ${REGISTRY}/pipeline-api:${TAG}
docker push ${REGISTRY}/pipeline-dashboard:${TAG}

# Update tags in k8s/overlays/prod/kustomization.yaml, then:
kubectl apply -k k8s/overlays/prod/
```

You will need to edit:
- `k8s/overlays/prod/kustomization.yaml` -- registry name and image tags
- `k8s/overlays/prod/ingress.yaml` -- domain
- `k8s/overlays/prod/patches/annotation-api-llm-config.yaml` -- LLM endpoint and model name
- `k8s/overlays/prod/patches/annotation-api-cors.yaml` -- CORS origin

## `overlays/hospital` -- hospital deployment package

Self-contained: edit one file (`config.env`), then run two scripts (`./build.sh` to build & push images, `./deploy.sh` to apply manifests). See [overlays/hospital/README.md](overlays/hospital/README.md).

This is the recommended path for handing off to a hospital IT team.

## LLM Endpoint

The platform does **not** deploy an LLM. It connects to an external OpenAI-compatible endpoint (e.g., vLLM serving Gemma 4) via two values:

- `VLLM_ENDPOINT` -- full URL with `/v1` suffix
- `VLLM_MODEL_NAME` -- model identifier expected by the endpoint

Both are set in the ConfigMap `annotation-api-config` (see each overlay's `annotation-api-llm-config.yaml` patch). The backend already supports `VLLM_MODEL_NAME` as an env var override via `backend/lib/vllm_runner.py`, so no code changes are required.

## Architecture

```
                    +---------- Ingress (prod / hospital) -------+
                    | /         => annotation-web                |
                    | /api      => annotation-api                |
                    | /pipeline => pipeline-dashboard            |
                    +--------------------------------------------+
                                  |
        +-------------------------+--------------------------+
        |                         |                          |
  annotation-web:3000     annotation-api:8001         pipeline-dashboard:8501
                                  |                          |
                                  v                          v
                      External LLM endpoint           pipeline-api:8000
                      (institution-managed)
```

## Why no vLLM Deployment?

The original Docker Compose stack includes a vLLM service for GPU-based LLM inference. In Kubernetes deployments where the hospital already serves their own LLM (via Run.ai, vLLM in another namespace, or a managed service), shipping a separate vLLM workload would duplicate infrastructure. The K8s manifests in this directory therefore deploy only the four CPU-only application services.

For the original GPU-included Docker setup, see the project root `docker-compose.yml` and `docker-compose.vllm.yml`.
