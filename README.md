# Socratic Tutor

A **neuro-symbolic study chatbot** where students ask their own questions across three tracks — Math, Coding, and Custom Textbook — and get Socratic guidance that is verified before it reaches them.

The neural layer (Vertex AI Gemini) drafts conversational hints. The symbolic layer (SymPy, Python AST + sandbox, RAG citation guards) checks those hints so final answers are not leaked and grounded claims stay faithful to uploaded textbooks.

---

## Features

- **Chat-first tutoring** — ask freely; optional practice problems are available as chips, not forced forms
- **Track 1 · Math** — SymPy equivalence + anti-leak scanning of tutor replies
- **Track 2 · Coding** — Python AST structure checks, anti-leak for full solutions, optional 2s sandbox tests
- **Track 3 · Textbook RAG** — PDF upload (≤15 pages / ≤5MB), `gemini-embedding-001` retrieval, verbatim citation guard
- **Multi-model router** — `gemini-3.1-flash-lite` → `gemini-3.5-flash-lite` → `gemini-3.7-flash` → `gemini-2.5-flash-lite`
- **Hybrid auth** — email/password (bcrypt + JWT) plus a real **Continue with Google** button (Google Identity Services → `/api/auth/google`)
- **React + Vite UI** — light green/orange chat interface with a live Neuro-Symbolic Audit drawer

---

## Architecture (4-Step Socratic Loop)

```text
Student chat message
        │
        ▼
 ground_truth_node     → load practice rules / open-chat mode / Top-3 RAG chunks
        │
        ▼
 neural_leap_node      → Vertex AI Gemini → NeuralSocraticDraft (JSON)
        │
        ▼
 symbolic_interrogation_node
   MATH → SymPy     ·  CODE → AST + sandbox  ·  RAG → similarity + verbatim quote
        │
   pass ──────────────► certified_output_node → reply to student
   fail + retry < 3 ──► critique + escalate model
   fail × 3 ──────────► circuit_breaker_node (deterministic fallback)
```

`MAX_SOCRATIC_RETRIES = 3`. Generative calls use structured JSON only (`tools=None`, no Google Search grounding).

**Serving model:** the React SPA is built in the Docker image and **served by the FastAPI backend** from `/app/static` (same origin `/api`). There is no separate frontend Cloud Run service in production.

---

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLModel, LangGraph, `google-genai` (Vertex AI) |
| Symbolic | SymPy, `ast`, subprocess sandbox, PyMuPDF + pgvector / SQLite fallback |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Monaco, KaTeX (built into the API image) |
| Deploy | Multi-stage Dockerfile (Node + Python), docker-compose, GitHub Actions → Cloud Run |

---

## Prerequisites

- Python 3.11+ (this repo was verified with 3.12)
- Node.js 20+ and npm
- Google Cloud project with Vertex AI enabled and ADC configured:

```powershell
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_GCP_PROJECT_ID
```

Copy `.env.example` to `.env` and set:

- `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`, `GOOGLE_GENAI_USE_VERTEXAI=true`
- `GOOGLE_CLIENT_ID` — OAuth **Web application** client ID from Google Cloud Console  
  Add Authorized JavaScript origin: `http://localhost:5173` (and your production frontend origin when deployed)

---

## Local development

### 1. Backend

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

- Liveness: http://127.0.0.1:8000/livez  
- Readiness: http://127.0.0.1:8000/health (checks DB)  
- OpenAPI: http://127.0.0.1:8000/docs (only when `DEBUG=true`)

### 2. Frontend

```powershell
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Open http://127.0.0.1:5173 — create an account, pick a track, and start chatting.

### 3. Tests

```powershell
.\.venv\Scripts\pytest.exe -v
cd frontend
npm run build
```

---

## Docker

```powershell
docker compose up --build
```

Services: Postgres + pgvector, FastAPI backend (`APP_ENV=development`, `DEBUG=true`), and optional Vite frontend for hot reload (see `docker-compose.yml`). The production image already embeds the SPA.

---

## Deploy and roll back

### One-time Secret Manager setup (GCP)

Create secrets once (values never go in GitHub plaintext env for JWT/DB):

```powershell
# Strong JWT secret
echo -n "REPLACE_WITH_LONG_RANDOM_SECRET" | gcloud secrets create JWT_SECRET_KEY --data-file=-

# Neon / Cloud SQL async URL, e.g. postgresql+psycopg://user:pass@host/db?sslmode=require
echo -n "postgresql+psycopg://..." | gcloud secrets create DATABASE_URL --data-file=-

# Grant the Cloud Run runtime service account access
gcloud secrets add-iam-policy-binding JWT_SECRET_KEY --member="serviceAccount:YOUR_SA@$PROJECT.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"
gcloud secrets add-iam-policy-binding DATABASE_URL --member="serviceAccount:YOUR_SA@$PROJECT.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"
```

GitHub Actions secrets still needed: `GCP_SA_KEY`, `GCP_PROJECT_ID` (optional), `GOOGLE_CLIENT_ID` (plain env on Cloud Run; leave empty to disable Google Sign-In).

Deploy injects:

- `--set-secrets=JWT_SECRET_KEY=JWT_SECRET_KEY:latest,DATABASE_URL=DATABASE_URL:latest`
- Plain env: `APP_ENV=production`, `DEBUG=false`, `GOOGLE_CLIENT_ID`, `CORS_ORIGINS=<Cloud Run URL>`

### Deploy (CI)

Push to `main`. The workflow builds the multi-stage image (Node SPA + Python API), deploys to Cloud Run, runs `scripts/smoke_post_deploy.py`, and on smoke failure routes 100% traffic back to the previous revision.

### Manual deploy

```powershell
$IMAGE = "us-central1-docker.pkg.dev/PROJECT/socratic-tutor/backend:manual"
docker build -t $IMAGE .
docker push $IMAGE
gcloud run deploy socratic-virtual-tutor-api `
  --image=$IMAGE `
  --region=us-central1 `
  --allow-unauthenticated `
  --min-instances=0 --max-instances=2 --memory=512Mi `
  --set-secrets="JWT_SECRET_KEY=JWT_SECRET_KEY:latest,DATABASE_URL=DATABASE_URL:latest" `
  --set-env-vars="APP_ENV=production,DEBUG=false,GOOGLE_GENAI_USE_VERTEXAI=true,GOOGLE_CLOUD_PROJECT=PROJECT,GOOGLE_CLOUD_LOCATION=us-central1,GOOGLE_CLIENT_ID=YOUR_WEB_CLIENT_ID"
$URL = gcloud run services describe socratic-virtual-tutor-api --region=us-central1 --format="value(status.url)"
gcloud run services update socratic-virtual-tutor-api --region=us-central1 --update-env-vars="CORS_ORIGINS=$URL"
python scripts/smoke_post_deploy.py --base-url $URL
```

Open `$URL` — the SPA and `/api` share that origin.

### Roll back traffic

```powershell
# List revisions
gcloud run revisions list --service=socratic-virtual-tutor-api --region=us-central1

# Send 100% traffic to a known-good revision
gcloud run services update-traffic socratic-virtual-tutor-api `
  --region=us-central1 `
  --to-revisions=REVISION_NAME=100
```

### Verify client IP rate-limit key on Cloud Run

With logger level DEBUG for `backend.app.services.rate_limit_service`, registration logs include `x_forwarded_for=... chosen_key=...` (last XFF hop).

---

## Repository layout

```text
AI--Tutor/
├── backend/app/          # FastAPI (API + SPA static), graph, symbolic, routers
├── frontend/src/         # React chat UI (built into /app/static in Docker)
├── scripts/              # Post-deploy smoke test
├── tests/                # pytest suites (auth, symbolic, graph/RAG, e2e, deploy)
├── document.md           # Master product/engineering specification
├── Dockerfile            # Node SPA build + Python runtime
├── docker-compose.yml
└── .github/workflows/    # CI + Cloud Run deploy + smoke/rollback
```

---

## License / notes

Built as a phase-gated neuro-symbolic tutor prototype for local and Cloud Run deployment. Keep secrets in `.env` / Secret Manager (never commit). Vertex AI usage should stay within your GCP credit budget — Flash-Lite cascade, bounded output tokens, and scale-to-zero Cloud Run (`min-instances=0`) are intentional cost controls.
