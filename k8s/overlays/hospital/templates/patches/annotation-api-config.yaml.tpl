apiVersion: v1
kind: ConfigMap
metadata:
  name: annotation-api-config
data:
  VLLM_ENDPOINT: "${VLLM_ENDPOINT}"
  VLLM_MODEL_NAME: "${VLLM_MODEL_NAME}"
  PYTHONUNBUFFERED: "1"
  HF_HOME: "/app/hf_cache"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: annotation-api
spec:
  template:
    spec:
      containers:
        - name: annotation-api
          env:
            - name: CORS_ORIGINS
              value: "https://${DOMAIN}"
