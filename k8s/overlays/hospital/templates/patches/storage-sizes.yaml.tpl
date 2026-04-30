apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: annotation-sessions
spec:
  resources:
    requests:
      storage: ${SESSIONS_STORAGE}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: annotation-faiss
spec:
  resources:
    requests:
      storage: ${FAISS_STORAGE}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: annotation-presets
spec:
  resources:
    requests:
      storage: ${PRESETS_STORAGE}
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: annotation-hf-cache
spec:
  resources:
    requests:
      storage: ${HF_CACHE_STORAGE}
