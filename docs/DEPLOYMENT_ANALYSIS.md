# ClinicalAnnotationWeb — Deployment Analysis & Hospital Fit Assessment

> **Purpose:** This document analyses the three supported deployment modes of the ClinicalAnnotationWeb platform, their respective pros and cons, and a structured questionnaire to help any hospital assess which mode is appropriate for their context.

---

## 1. System Architecture Overview

Before comparing deployment modes it is worth understanding what is actually being deployed:

| Component | Technology | Port | Role |
|-----------|-----------|------|------|
| `annotation-api` | FastAPI (Python 3.11) | 8001 | Backend API — session management, LLM orchestration, CSV import/export |
| `annotation-web` | Next.js 14 (React 18) | 3000 | Annotation UI — human-in-the-loop review interface |
| `pipeline-api` | FastAPI (Python 3.11) | 8010 | NLP pipeline coordination — batch ingestion and result aggregation |
| `pipeline-dashboard` | Streamlit | 8501 | Pipeline monitoring dashboard |
| `vllm` | vLLM (OpenAI-compatible) | 8000/8080 | LLM inference server — **requires NVIDIA GPU** |

### Data flow

```
CSV upload (clinical notes + patient IDs)
       ↓
annotation-api  ←→  vLLM (MedGemma 27B by default)
       ↓
Sessions stored as plain JSON files on disk (backend/sessions/)
       ↓
Human annotator reviews and corrects in annotation-web
       ↓
Export: pipeline-compatible CSV with ICD-O-3 codes + IDEA4RC data model fields
```

### Storage model

There is **no database**. All session state is persisted as `.json` files under `backend/sessions/`. This is a key architectural decision that affects all deployment modes.

### Security posture (as-shipped)

| Control | Status |
|---------|--------|
| Authentication | **None** — all API endpoints are open |
| Authorization (RBAC) | **None** |
| Encryption at rest | **None** — JSON files are plain text |
| Encryption in transit (TLS) | Not configured — HTTP only by default |
| Audit logging | **None** |
| CORS | Restricted to `localhost:3000/3001` by default; extendable via `CORS_ORIGINS` env var |
| Container non-root user | Yes (UID 1001 in all Dockerfiles) |
| Prometheus metrics | Exposed at `/metrics` (no auth guard) |

> **Critical note for hospitals:** The platform as-shipped has **no authentication layer**. PHI (patient text in clinical notes, patient IDs, dates) flows through the system without any access control. Any deployment in a clinical environment **must** add an authentication proxy or identity-aware ingress in front of the services.

---

## 2. Deployment Mode A — Local / Bare-Metal (Native)

### What it is

Running the services directly on a server or workstation using the native Python and Node.js runtimes:

```bash
# Backend
cd backend && uvicorn main:app --reload --port 8001

# Frontend
cd frontend && npm run dev

# vLLM (separate GPU machine or same)
vllm serve unsloth/medgemma-27b-text-it-unsloth-bnb-4bit
```

### Prerequisites

- Python 3.11+ (with pip)
- Node.js 18+ (with npm)
- CUDA-capable NVIDIA GPU (≥ 24 GB VRAM recommended for MedGemma-27B-4bit)
- CUDA 12.x toolkit and NVIDIA drivers
- HuggingFace access token (to download the model on first run)

### Pros

| # | Benefit | Why it matters |
|---|---------|---------------|
| 1 | **Simplest to start** | A single researcher can have the system running in < 1 hour with no infrastructure knowledge |
| 2 | **Direct debugging** | Full access to logs, Python debugger, hot-reload; ideal for prompt engineering and model experimentation |
| 3 | **No container overhead** | Marginally better GPU memory efficiency; no Docker GPU passthrough configuration |
| 4 | **Fastest iteration cycle** | Code changes are reflected immediately (uvicorn `--reload`, Next.js hot-reload) |
| 5 | **Works offline after initial model download** | Once the HuggingFace cache is warm the system runs air-gapped |

### Cons

| # | Risk | Severity |
|---|------|----------|
| 1 | **No isolation** — processes run as the logged-in user; a bug or exploit has full filesystem access | High |
| 2 | **No reproducibility** — Python/Node version drift, OS patches can break the installation | Medium |
| 3 | **Single point of failure** — no process supervision; if uvicorn crashes, annotations stop | High |
| 4 | **No access control** — the API is reachable by anyone on the same network | Critical |
| 5 | **Manual updates** — no rolling restart, downtime required for any change | Medium |
| 6 | **Session data on local disk** — no backup, no redundancy | High |
| 7 | **Large dependency footprint** — `requirements.txt` is 183 packages including CUDA libraries, PyTorch, vLLM; conflicts with other projects are likely | Medium |

### Suitable for

- Single-researcher proof-of-concept on a dedicated GPU workstation
- Offline annotation campaigns with one active user at a time
- Development and prompt engineering

---

## 3. Deployment Mode B — Docker Compose

### What it is

Three Compose files are provided:

| File | Purpose |
|------|---------|
| `docker-compose.yml` | **Production** — four services in an isolated bridge network with named volumes |
| `docker-compose.dev.yml` | **Development overlay** — mounts source code for hot-reload without rebuilding images |
| `docker-compose.vllm.yml` | **GPU extension** — adds the vLLM container to the stack with NVIDIA runtime; requires `docker-compose -f docker-compose.yml -f docker-compose.vllm.yml up` |
| `pipeline/docker-compose.yml` | **Pipeline standalone** — deploys only the pipeline services independently |

Key design decisions in the Compose files:
- Internal `clinical-network` bridge — services communicate by name, never expose internal ports externally except through explicit `ports:` mappings
- Named volumes `annotation-sessions` and `pipeline-results` — data survives container restarts
- Health checks on `annotation-api` (checks `/api/server/status` every 30 s)
- `annotation-web` waits for `annotation-api` to be healthy before starting
- All containers run as non-root (UID 1001)

### Pros

| # | Benefit | Why it matters |
|---|---------|---------------|
| 1 | **Reproducible environment** | The same image runs identically on any Docker host; eliminates "works on my machine" |
| 2 | **Process supervision** | `restart: unless-stopped` ensures automatic recovery after crashes or reboots |
| 3 | **Network isolation** | Services are isolated on a private bridge; only explicitly mapped ports are reachable from outside |
| 4 | **Data persistence with named volumes** | Session JSON files survive container rebuilds; volumes can be snapshotted |
| 5 | **Multi-service orchestration** | Health-check dependencies ensure the UI does not start before the API is ready |
| 6 | **Easy to update** | `docker compose pull && docker compose up -d` with minimal downtime |
| 7 | **Dev/prod parity** | The dev overlay uses the same images with source mounts — same Python version, same libs |
| 8 | **GPU support built-in** | `docker-compose.vllm.yml` handles NVIDIA runtime, GPU allocation, and model caching |

### Cons

| # | Risk | Severity |
|---|------|----------|
| 1 | **Still no authentication** — ports 3000 and 8001 are open to the Docker host's network | Critical |
| 2 | **Single host only** — Compose does not span multiple machines; no horizontal scaling | Medium |
| 3 | **No secrets management** — environment variables (HF token, CORS origins) are in plain `.env` files | High |
| 4 | **No TLS** — traffic between browser and the stack is HTTP; PHI travels in clear text | High |
| 5 | **Volume backup is manual** — no built-in snapshot or backup policy for `annotation-sessions` | High |
| 6 | **GPU driver must match on host** — NVIDIA CUDA version on the host must be ≥ CUDA version in the image | Medium |
| 7 | **Large image sizes** — the backend image bundles PyTorch + vLLM + CUDA bindings; first build is slow and images are multi-GB | Low |
| 8 | **Docker-in-Docker not supported** — cannot run inside an existing container without privileged mode | Low |

### Suitable for

- Small-to-medium annotation teams (3–20 users) on a dedicated hospital server or VM
- Environments where a sysadmin can add an nginx/Caddy reverse proxy with TLS and basic auth in front
- Semi-production deployments within a firewalled hospital research network
- Any site that cannot or will not run Kubernetes

---

## 4. Deployment Mode C — Kubernetes / Helm Capsule

### What it is

The application images (built from the same Dockerfiles) are deployed inside a **capsule** — a pre-configured, security-hardened Kubernetes environment provided as a Helm chart (external to this repository). The capsule concept implies:

- Namespace isolation with Kubernetes RBAC
- NetworkPolicies restricting inter-pod communication
- Secrets injected via Kubernetes Secrets (or a vault integration)
- An ingress controller with TLS termination (cert-manager, hospital PKI)
- PersistentVolumeClaims backed by a storage class (NFS, Ceph, cloud block storage)
- An identity-aware proxy or SSO integration (Keycloak, Azure AD, hospital IdP)
- GPU nodes with the NVIDIA device plugin for vLLM scheduling

### Codebase readiness assessment

The codebase is architecturally well-suited for Kubernetes in the following ways:

| Aspect | Current state | K8s readiness |
|--------|--------------|---------------|
| Containerisation | Full Dockerfiles, non-root | Ready |
| Health checks | `/api/health` and `/api/server/status` | Ready for liveness/readiness probes |
| Configuration via env vars | `VLLM_ENDPOINT`, `CORS_ORIGINS`, `NEXT_PUBLIC_API_URL`, `HF_TOKEN` | Ready for K8s Secrets / ConfigMaps |
| Stateless compute | API is stateless (state = JSON on disk) | Ready |
| Prometheus metrics | `/metrics` endpoint exposed | Ready for Prometheus scraping |
| Multi-stage frontend build | Standalone Next.js output | Ready |
| No hardcoded secrets | Configuration via env/config files | Ready |

Items that would need attention before/during Helm packaging:

| Gap | Mitigation in capsule |
|----|----------------------|
| JSON file storage is not replicated | PVC with `ReadWriteMany` storage class, or migrate to a database (PostgreSQL) for multi-replica support |
| No authentication built in | Handled at ingress layer (OIDC proxy) by the capsule |
| No audit log | Capsule-level audit (Kubernetes audit log, Falco) or add structured logging to the API |
| `NEXT_PUBLIC_API_URL` is baked at build time | The Next.js Dockerfile uses `standalone` output — the URL must be set at build time or via runtime injection |
| vLLM needs GPU nodes | Helm values should target a GPU node pool via `nodeSelector` / `tolerations` |

### Pros

| # | Benefit | Why it matters |
|---|---------|---------------|
| 1 | **Enterprise security handled at platform level** — authentication, TLS, network policy are capsule responsibilities | Removes the biggest compliance gap |
| 2 | **High availability** — Kubernetes can restart failed pods, spread replicas across nodes | Annotation campaigns are not interrupted by individual failures |
| 3 | **Horizontal scaling** — annotation-api and annotation-web pods can be scaled out (with shared PVC) | Supports large annotation teams simultaneously |
| 4 | **Secrets management** — HuggingFace token, internal URLs never appear in plain text | GDPR/HIPAA-relevant |
| 5 | **Observability** — Prometheus + Grafana dashboards, centralized logging (Loki/ELK) | Hospital IT can monitor the system |
| 6 | **Upgrade with zero downtime** — rolling deployments, canary releases | No annotation session loss during updates |
| 7 | **Backup via storage class** — PVC snapshots via Velero or cloud-native CSI drivers | Protects session data |
| 8 | **Multi-tenant ready** — namespace isolation allows different departments or studies | Research governance per project |
| 9 | **Fits existing hospital K8s governance** — the capsule pattern means the hospital's InfoSec has already approved the base platform | Shorter approval path |

### Cons

| # | Risk | Severity |
|---|------|----------|
| 1 | **Highest operational complexity** — requires Kubernetes expertise to operate and troubleshoot | High (for small IT teams) |
| 2 | **JSON-file storage limits multi-replica deployments** — session files need a shared `ReadWriteMany` volume or DB migration | Medium |
| 3 | **GPU scheduling complexity** — vLLM pods need specific node selectors, resource limits, and NVIDIA device plugin | High |
| 4 | **`NEXT_PUBLIC_API_URL` baked at build time** — the internal cluster URL vs. external URL must be managed carefully in Helm values | Medium |
| 5 | **External capsule dependency** — the hospital's InfoSec/ops team controls the capsule release cycle; updates may be slow | Medium |
| 6 | **Model download at startup** — 27B model download from HuggingFace in an air-gapped cluster requires a local model registry (MinIO, Harbor) | High for air-gapped sites |
| 7 | **Cold-start time** — vLLM loads a large model; K8s liveness probes must have a long `initialDelaySeconds` | Low (operational) |

### Suitable for

- Hospitals with an existing Kubernetes platform (OpenShift, Rancher, AKS, EKS, GKE, on-prem K8s)
- Multi-departmental or multi-center annotation campaigns
- Production deployments where PHI compliance is audited
- Sites already using the capsule platform for other applications

---

## 5. Comparative Summary

| Criterion | Local / Bare-metal | Docker Compose | Kubernetes Capsule |
|-----------|--------------------|----------------|--------------------|
| **Setup effort** | Low | Medium | High |
| **Ops expertise needed** | Python/Linux admin | Docker admin | Kubernetes engineer |
| **Authentication** | None (add manually) | None (add reverse proxy) | Yes (capsule provides) |
| **TLS / HTTPS** | None | None (add nginx) | Yes (ingress) |
| **Data encryption at rest** | None | None | Depends on storage class |
| **Audit logging** | None | None | Platform-level |
| **HA / fault tolerance** | None | restart policy only | Yes |
| **Horizontal scaling** | No | No | Yes (with shared storage) |
| **GPU support** | Direct (CUDA) | Via Docker NVIDIA runtime | Via device plugin |
| **Secret management** | Plain `.env` | Plain `.env` | K8s Secrets / Vault |
| **Backup** | Manual | Manual volume backup | Velero / CSI snapshots |
| **PHI compliance readiness** | Low | Low–Medium | High (with capsule) |
| **Suitable team size** | 1–2 researchers | 3–20 annotators | 10–100+ annotators |

---

## 6. Hospital Fit Assessment Questionnaire

Use the following questions to determine which deployment mode is right for your institution:

### 6.1 Regulatory and Compliance

- **Q1.** Does your institution process real patient records (PHI) in this platform, or only de-identified/synthetic data?
  - *PHI → Kubernetes capsule required; de-identified → any mode may be acceptable.*

- **Q2.** Are you subject to GDPR, HIPAA, or national health data regulations that require access control and audit trails?
  - *Yes → Kubernetes capsule (provides audit at platform level) or Docker Compose with an authenticated reverse proxy.*

- **Q3.** Does your institution's Data Protection Officer (DPO) require a Data Protection Impact Assessment (DPIA) before deployment?
  - *Yes → Engage DPO early; the lack of built-in auth will be a finding under all three modes.*

### 6.2 Infrastructure and IT

- **Q4.** Do you have an existing Kubernetes cluster (or managed K8s service) operated by your IT department?
  - *Yes → Capsule mode. No → Docker Compose or local.*

- **Q5.** Is the target server air-gapped (no internet access)?
  - *Yes → You must pre-download the MedGemma model and serve it from a local registry (MinIO/Harbor). This is feasible in all modes but requires extra setup.*

- **Q6.** Does your institution have NVIDIA GPUs available for the inference server?
  - *No GPU → The system cannot run LLM inference. You would need to connect to an external vLLM endpoint or switch to a CPU-compatible model.*

- **Q7.** What is your IT team's container expertise?
  - *Docker only → Compose. Kubernetes → Capsule. Neither → Local.*

### 6.3 Security Requirements

- **Q8.** Must all access to the annotation UI be behind Single Sign-On (SSO) / hospital identity provider (e.g., Azure AD, LDAP)?
  - *Yes → Kubernetes capsule (OIDC proxy at ingress) or Docker Compose with an SSO-capable reverse proxy (Authelia, Keycloak + nginx).*

- **Q9.** Is the server network-isolated from the general hospital network?
  - *No isolation → Any exposure of ports 3000 and 8001 to the hospital network without auth is a critical risk.*

- **Q10.** Does your policy require encryption of data at rest?
  - *Yes → The current JSON file storage is plain text. You need encrypted storage volumes (LUKS at OS level, encrypted PVCs in K8s) in any mode.*

### 6.4 Operational Requirements

- **Q11.** How many concurrent annotators do you expect?
  - *1–3 → Local. 4–20 → Docker Compose. 20+ → Kubernetes.*

- **Q12.** What is the acceptable downtime for planned maintenance?
  - *Zero downtime required → Kubernetes only.*

- **Q13.** Do you need multi-center or multi-department isolation (separate studies that cannot see each other's sessions)?
  - *Yes → Kubernetes (separate namespaces or capsule instances) or separate Docker Compose deployments.*

- **Q14.** Do you need a long-term archive of annotation sessions beyond the active project?
  - *Yes → Implement a backup strategy regardless of mode: volume snapshots, S3 exports, or migrate sessions to a database.*

### 6.5 Model and AI Considerations

- **Q15.** Do you accept MedGemma (Google DeepMind) as the inference model, or does your institution require a locally-hosted, fully on-premise model with no external license dependency?
  - *External model unacceptable → Evaluate alternative models compatible with vLLM and your clinical domain.*

- **Q16.** Does your ethics committee or IRB need to approve the use of LLM-extracted data in downstream analyses?
  - *Yes → Ensure the annotation workflow includes a mandatory human review step (the platform supports this but it is not enforced).*

---

## 7. Recommended Decision Path

```
Does your hospital already run a Kubernetes capsule platform?
├── Yes → Use CAPSULE MODE. Engage the capsule operator team to package the images.
│          Add a PVC-backed shared volume for sessions/.
│          Ensure the HuggingFace model is mirrored locally if air-gapped.
│
└── No
    ├── Is this a proof-of-concept / single researcher?
    │   └── Yes → LOCAL MODE. Use a dedicated GPU workstation.
    │              Keep the server behind a firewall or VPN.
    │
    └── Is this a departmental deployment for a team of annotators?
        └── Yes → DOCKER COMPOSE + reverse proxy.
                   Add nginx/Caddy with:
                   - TLS certificate (hospital PKI or Let's Encrypt)
                   - HTTP Basic Auth or OIDC proxy (Authelia)
                   - Restrict port 8001 to internal network only
                   - Enable OS-level disk encryption for the session volume
```

---

## 8. Immediate Gaps to Address Before Any Clinical Deployment

Regardless of deployment mode, the following gaps must be resolved before processing real patient data:

1. **Authentication** — Add an identity provider integration or at minimum HTTP Basic Auth at the reverse proxy level. The API has zero access control today.

2. **TLS termination** — All traffic must be HTTPS. Never expose port 3000 or 8001 directly.

3. **Encryption at rest** — Enable filesystem encryption (LUKS, BitLocker, encrypted PVC) for the volume where `backend/sessions/` lives.

4. **Backup** — Implement automated daily snapshots of the sessions volume.

5. **Audit logging** — Add structured access logs (already partially available via uvicorn access logs and Prometheus metrics, but no user-level audit trail exists).

6. **Network segmentation** — The annotation server must not be reachable from general hospital workstations without going through the authenticated proxy.

7. **Model governance** — Document which model version (name + commit hash) was used for each annotation session. The current system stores `model_name` but not model version/hash.

---

*Document generated by code analysis of ClinicalAnnotationWeb — 2026-02-27*
