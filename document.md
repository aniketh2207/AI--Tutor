# MASTER SPECIFICATION: NEURO-SYMBOLIC SOCRATIC VIRTUAL TUTOR

## 1. SYSTEM OVERVIEW & CORE PHILOSOPHY
The **Neuro-Symbolic Socratic Virtual Tutor** is an end-to-end EdTech SaaS platform where students register/login, enroll in specialized learning tracks, and solve problems guided by a 4-step **Neuro-Symbolic Socratic Loop** orchestrated by **LangGraph**.

Unlike standard LLM wrappers that hallucinate steps or give away final answers, this system separates **Natural Language Intuition (Neural Layer via Gemini API)** from **Deterministic Verification (Symbolic Layer via SymPy, Python AST, and Verbatim RAG Citation Guards)**. The student never sees a response until the Symbolic Layer certifies 100% logical/mathematical compliance and 0% final-answer leakage.

### The 4-Step Socratic Cycle (LangGraph Topology)
1. **Step 1 — Intuitive Leap (Neural Node):** Parses the student's input, extracts a machine-verifiable hypothesis of their work, and drafts a Socratic guiding question/hint.
2. **Step 2 — Socratic Interrogation (Symbolic Node):** Runs deterministic verification against the ground-truth engine (`SymPy`, `Python AST`, or `RAG Substring/Threshold Guard`) AND checks that the drafted hint does not leak the final answer.
3. **Step 3 — Correction & Alignment (Conditional Loop):** If Step 2 fails, the Symbolic Node injects a structured critique (`"Rule Y violated: ..."`), routing back to the Neural Node to regenerate (capped at `MAX_SOCRATIC_RETRIES = 3`, followed by a deterministic circuit-breaker fallback).
4. **Step 4 — Certified Output:** Releases the verified Socratic response and full loop telemetry (for the UI's Live Neuro-Symbolic Audit Drawer) to the student.

---

## 2. LOCKED TECH STACK & CONSTRAINTS
- **Backend:** Python 3.11+, FastAPI, SQLModel (SQLAlchemy 2.0 + Pydantic v2), `psycopg[binary,pool]` (async).
- **State Orchestration:** `langgraph>=0.2.50` (`StateGraph`) + `langgraph-checkpoint-postgres` (`AsyncPostgresSaver`).
- **Neural SDK:** Official `google-genai` SDK (`from google import genai`). **Forbidden:** `langchain-google-genai`, `google-generativeai` (legacy).
- **Symbolic Engines:**
  - **Track 1 (Mathematics):** `sympy>=1.13` (Algebra, Calculus, Linear Algebra equivalence + leak detection).
  - **Track 2 (Python & DSA Logic):** Built-in `ast` module (structural node verification) + isolated `subprocess.run` with `timeout=2.0` seconds for I/O assertions.
  - **Track 3 (Custom Textbook RAG):** `PyMuPDF` (`fitz`) for PDF extraction + `gemini-embedding-001` (768-dim vectors) + `pgvector` cosine similarity (`>= 0.65` threshold) + deterministic verbatim quote substring verification.
- **Database:** Neon Serverless PostgreSQL (with `CREATE EXTENSION IF NOT EXISTS vector;`) for Users, Enrollments, RAG Vectors, and LangGraph Checkpoints. For local `pytest` unit tests, support an isolated test schema or SQLite/mock fallback where vector ops are mocked.
- **Authentication:** Hybrid Auth — Local Email/Password (Bcrypt + JWT Bearer tokens) AND Google OAuth2 ID-token verification (`google-auth`).
- **Frontend:** React 18 (Vite + TypeScript), Tailwind CSS, `lucide-react`, `katex` / `react-katex` (Math), `@monaco-editor/react` (Python code), Axios.
- **Deployment:** Multi-stage CPU-only `Dockerfile` (`python:3.11-slim`), GitHub Actions CI/CD, Google Cloud Run (`min-instances=0`, `max-instances=2`), Vercel/Firebase for Frontend.

---

## 3. MULTI-MODEL GEMINI ROUTER & COST GUARDRAILS
All runtime LLM calls must pass through `backend/app/services/gemini_router.py`.
- **Cascade Order:**
  1. `gemini-3.1-flash-lite` (Primary — Attempt 1)
  2. `gemini-3.5-flash-lite` (Secondary — Attempt 2 / Step 3 Symbolic Retry)
  3. `gemini-3.7-flash` (Tertiary — Attempt 3 Escalation)
  4. `gemini-2.5-flash-lite` (Emergency Rate-Limit/503 Fallback)
- **Embeddings Model:** `gemini-embedding-001` (Output dimensionality: `768`).
- **Strict Rules:**
  - Every generative call MUST enforce `response_mime_type="application/json"` and `response_schema=NeuralSocraticDraft`.
  - NEVER enable `google_search` tools.
  - Catch `APIError`, `ClientError` (429/503), and `ValidationError`, automatically failing over to the next model in the cascade and logging the exact model used in `ModelTelemetry`.

---

## 4. REPOSITORY DIRECTORY STRUCTURE
Cursor must maintain this exact repository layout:

```text
socratic-tutor/
├── .cursorrules
├── document.md
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── .github/workflows/ci_cd.yml
├── handoff_audit/
│   ├── AGENT_EXECUTION_LOG.md      # Cursor's mandatory self-documentation log
│   ├── PROMPT_LEDGER.md            # Architect's prompt log & phase sign-offs
│   └── VERIFICATION_GATES.md       # Automated test & coverage results per phase
├── backend/
│   ├── requirements.txt
│   ├── pytest.ini
│   └── app/
│       ├── main.py                 # FastAPI entry + lifespan + CORS + OpenAPI export
│       ├── config.py               # Pydantic Settings (.env loader)
│       ├── database.py             # Async SQLModel engine + pgvector init
│       ├── models/                 # SQLModel DB tables
│       │   ├── user.py             # User, SubjectEnrollment
│       │   ├── curriculum.py       # ProblemItem, TextbookChapter, DocumentChunk
│       │   └── session.py          # TutorSession, SocraticTurnLog
│       ├── schemas/                # Strict Pydantic v2 API & Neuro-Symbolic contracts
│       │   ├── auth.py
│       │   ├── socratic.py         # NeuralSocraticDraft, SymbolicVerdict, TurnResponse
│       │   └── rag.py
│       ├── services/
│       │   ├── auth_service.py     # JWT + Google OAuth verification
│       │   ├── gemini_router.py    # Multi-model fallback cascade + telemetry
│       │   └── rag_ingestion.py    # PyMuPDF parser + chunker + gemini-embedding-001
│       ├── symbolic/               # Deterministic Verifiers (0% LLM)
│       │   ├── math_verifier.py    # SymPy equivalence & answer-leak detector
│       │   ├── ast_verifier.py     # Python AST node inspector & 2s sandbox runner
│       │   └── rag_verifier.py     # Verbatim quote & similarity threshold guard
│       ├── graph/                  # LangGraph Orchestration
│       │   ├── state.py            # SocraticGraphState TypedDict
│       │   ├── nodes.py            # ground_truth, neural_leap, symbolic_judge, circuit_breaker
│       │   └── workflow.py         # StateGraph builder + AsyncPostgresSaver
│       └── routers/
│           ├── auth.py
│           ├── subjects.py
│           ├── tutor.py            # Socratic turn execution & audit retrieval
│           └── rag.py              # PDF upload & textbook chapter listing
├── tests/
│   ├── test_handoff_governance.py  # Enforces AGENT_EXECUTION_LOG.md completeness
│   ├── test_auth_and_router.py     # Phase 1 gate
│   ├── test_symbolic_math_ast.py   # Phase 2 gate
│   ├── test_socratic_graph_rag.py  # Phase 3 gate
│   └── test_e2e_api_contract.py    # Phase 4/5 gate
└── frontend/
    ├── package.json
    ├── vite.config.ts
    ├── tailwind.config.js
    └── src/
        ├── types/api.ts            # Synced with FastAPI Pydantic schemas
        ├── components/
        │   ├── AuthModal.tsx
        │   ├── SubjectDashboard.tsx
        │   ├── MathWorkspace.tsx
        │   ├── CodeWorkspace.tsx
        │   ├── RagWorkspace.tsx
        │   └── NeuroSymbolicAuditDrawer.tsx  # Live 4-step loop visualizer
        └── App.tsx
```

---

## 5. CORE DATA SCHEMAS & CONTRACTS (ZERO AMBIGUITY)

### 5.1 The Neuro-Symbolic JSON Contract (`backend/app/schemas/socratic.py`)
Every call to the Gemini Router inside the LangGraph `neural_leap_node` MUST enforce this Pydantic schema:

```python
from pydantic import BaseModel, Field
from typing import Optional, List, Literal

class NeuralSocraticDraft(BaseModel):
    student_intent_summary: str = Field(description="Brief analysis of what the student attempted.")
    student_symbolic_claim: str = Field(
        description="For MATH: valid SymPy expression representing the student's current step (e.g., '3*x**2'). "
                    "For CODE: the Python snippet submitted. "
                    "For RAG: key claim extracted from student's text."
    )
    is_final_goal_reached_claim: bool = Field(
        description="True ONLY if the student explicitly arrived at the complete final answer."
    )
    cited_chunk_id: Optional[int] = Field(
        default=None, description="REQUIRED for RAG track: exact ID of the retrieved textbook chunk."
    )
    verbatim_quote: Optional[str] = Field(
        default=None, description="REQUIRED for RAG track: exact 100% verbatim substring from the chunk supporting the hint."
    )
    socratic_question: str = Field(
        description="The guiding Socratic question or hint for the student. MUST NOT contain or leak the final answer."
    )

class SymbolicVerdict(BaseModel):
    iteration: int
    passed: bool
    student_step_correct: bool
    answer_leaked_in_hint: bool
    rejection_reason: Optional[str] = None
    symbolic_rule_checked: str
    model_used: str
    latency_ms: float

class SocraticTurnResponse(BaseModel):
    session_id: str
    track: Literal["MATH", "CODE", "RAG"]
    socratic_reply: str
    problem_solved: bool
    iterations_taken: int
    circuit_breaker_triggered: bool
    audit_trail: List[SymbolicVerdict]
```

### 5.2 Deterministic Symbolic Verifier Specifications (All 3 Tracks)

1. **Track 1 — `math_verifier.py` (`SymPy`):**
   - Each seeded Math problem defines `target_expr` (e.g., `"3*x**2 + 2"`) and `allowed_intermediate_exprs` (e.g., `["3*x**2", "2"]`).
   - **Step Check:** Parse `student_symbolic_claim` via `sympy.sympify()`. Check algebraic equivalence against `target_expr` or `allowed_intermediate_exprs` via `sympy.simplify(claim - target) == 0`.
   - **Anti-Leak Check:** Scan `socratic_question` using regex/math-token extraction + `sympify`. If the student has NOT yet solved the problem (`student_step != target_expr`), and `socratic_question` contains the simplified `target_expr` string or an equivalent symbolic expression, set `passed = False`, `answer_leaked_in_hint = True`, and `rejection_reason = "LEAK VIOLATION: Your Socratic hint revealed the final answer ('{target_expr}'). Rephrase as a guiding question without stating the solution."`

2. **Track 2 — `ast_verifier.py` (`Python AST` + Subprocess):**
   - Each seeded Coding problem defines `required_ast_nodes` (e.g., `["For", "Return"]`), `forbidden_ast_nodes` (e.g., `["While"]`), `forbidden_calls` (e.g., `["sum", "sort"]`), and `test_cases`.
   - **Structural Check:** Parse student code with `ast.parse()`. Verify required/forbidden AST nodes and function calls without executing code.
   - **Anti-Leak Check:** Scan `socratic_question` for markdown code blocks (` ```python `) or lines that parse as valid multi-line function definitions (`ast.FunctionDef`). If the LLM tries to hand over full working code in the hint, reject immediately (`answer_leaked_in_hint = True`).
   - **Sandbox Execution:** Only if AST structural rules pass, run the student's function against `test_cases` inside `subprocess.run(["python", "-I", "-c", runner_script], timeout=2.0, capture_output=True)`.

3. **Track 3 — `rag_verifier.py` (Grounded Textbook Verifier):**
   - On PDF upload (`max 15 pages / 5MB`), extract text per page with `PyMuPDF`, split into 600-character chunks (100-char overlap), embed via `gemini-embedding-001` (`output_dimensionality=768`), and save to Neon `DocumentChunk`.
   - During a Socratic turn, retrieve Top-3 chunks using `pgvector` cosine similarity.
   - **Out-of-Scope Check:** If `max_similarity < 0.65`, bypass the LLM or reject out-of-domain synthesis.
   - **Verbatim Citation Check:** Verify `cited_chunk_id` exists in the Top-3 chunks AND `verbatim_quote.strip() in chunk.content` (case-normalized whitespace match). If the LLM hallucinated or paraphrased the quote, set `passed = False` and `rejection_reason = "CITATION VIOLATION: verbatim_quote must be an exact character-for-character substring of the retrieved chunk."`
   - **Anti-Leak Check:** Ensure `socratic_question` does not verbatim-copy more than 60% of the target answer span before the student identifies the core concept.

---

## 6. LANGGRAPH WORKFLOW SPECIFICATION (`backend/app/graph/`)

Define `SocraticGraphState(TypedDict)`:
- `session_id: str`
- `track: Literal["MATH", "CODE", "RAG"]`
- `problem_payload: dict`
- `student_input: str`
- `retrieved_chunks: list[dict]`
- `iteration: int`
- `latest_draft: Optional[dict]`
- `audit_trail: list[dict]`
- `final_reply: str`
- `problem_solved: bool`
- `circuit_breaker_triggered: bool`

### Graph Nodes & Edges:
1. `START -> ground_truth_node`: Initializes `iteration = 0`, `audit_trail = []`, loads problem rules or retrieves `pgvector` chunks.
2. `ground_truth_node -> neural_leap_node`: Calls `gemini_router.generate_socratic_draft()`. If `iteration > 0`, appends the previous `SymbolicVerdict.rejection_reason` to the prompt so the neural layer self-corrects (Step 3).
3. `neural_leap_node -> symbolic_interrogation_node`: Runs `math_verifier`, `ast_verifier`, or `rag_verifier` (Step 2). Appends `SymbolicVerdict` to `audit_trail` and increments `iteration += 1`.
4. **Conditional Edge (`route_after_interrogation`):**
   - If `audit_trail[-1]["passed"] is True` -> `certified_output_node` (Step 4).
   - If `audit_trail[-1]["passed"] is False` and `iteration < 3` -> `neural_leap_node` (Step 3 Retry).
   - If `audit_trail[-1]["passed"] is False` and `iteration >= 3` -> `circuit_breaker_node` (Generates a deterministic, rule-based Socratic prompt without calling the LLM again, setting `circuit_breaker_triggered = True`).
5. `certified_output_node / circuit_breaker_node -> END`.

---

## 7. PHASE-BY-PHASE IMPLEMENTATION & VERIFICATION GATES

Cursor must execute these 6 Phases sequentially, stopping after each Phase for Human Architect verification.

### PHASE 0: Repository Governance, Audit Harness & Environment Setup
- **Tasks:**
  1. Create directory tree, `.env.example`, `backend/requirements.txt`, `pytest.ini`.
  2. Create `/handoff_audit/AGENT_EXECUTION_LOG.md`, `/handoff_audit/PROMPT_LEDGER.md`, and `/handoff_audit/VERIFICATION_GATES.md`.
  3. Build `tests/test_handoff_governance.py`: A pytest suite that checks `AGENT_EXECUTION_LOG.md` contains required headers (`Spec Comprehension Check`, `Architectural Decisions & Ambiguity Log`, `Failure & Self-Correction Ledger`, `Verification Evidence`) for every completed phase.
- **Verification Gate 0:** Run `pytest tests/test_handoff_governance.py` -> 100% Pass. **STOP & WAIT FOR APPROVAL.**

### PHASE 1: Core Backend, Database, Hybrid Auth & Multi-Model Router
- **Tasks:**
  1. Implement `config.py`, `database.py` (SQLModel + Neon Postgres / SQLite test fallback), and DB models (`User`, `SubjectEnrollment`, `ProblemItem`, `TutorSession`, `SocraticTurnLog`).
  2. Implement `auth_service.py` and `routers/auth.py` (`/api/auth/register`, `/api/auth/login`, `/api/auth/google`, `/api/auth/me`) + `routers/subjects.py` (enroll & seed default Math and Coding curriculum problems).
  3. Implement `gemini_router.py` with the 4-model cascade (`gemini-3.1-flash-lite` -> `gemini-3.5-flash-lite` -> `gemini-3.7-flash` -> `gemini-2.5-flash-lite`).
  4. Write `tests/test_auth_and_router.py` testing JWT registration/login, Google token mock verification, subject enrollment, and simulated 429 rate-limit fallback across the 4 Gemini models.
- **Verification Gate 1:** `pytest` passes all Phase 0 & Phase 1 tests. Log results in `AGENT_EXECUTION_LOG.md`. **STOP & WAIT FOR APPROVAL.**

### PHASE 2: Symbolic Verifiers (`SymPy` & `Python AST`)
- **Tasks:**
  1. Implement `symbolic/math_verifier.py` (algebraic/calculus equivalence + final-answer leak detector).
  2. Implement `symbolic/ast_verifier.py` (AST structural node inspection, forbidden call detection, code-leak blocker, and 2-second isolated subprocess test runner).
  3. Write `tests/test_symbolic_math_ast.py` covering: valid intermediate math steps, leaked final answers in hints (must fail verification), valid/invalid AST structures, infinite loop `while True: pass` timeout handling (must terminate in <= 2.5 seconds), and code-block leak rejection.
- **Verification Gate 2:** `pytest` passes 100% of Phase 0–2 tests. Log results in `AGENT_EXECUTION_LOG.md`. **STOP & WAIT FOR APPROVAL.**

### PHASE 3: Grounded RAG Engine & LangGraph Socratic State Machine
- **Tasks:**
  1. Implement `services/rag_ingestion.py` (`PyMuPDF` text extraction + chunking + `gemini-embedding-001` 768-dim embeddings) and `symbolic/rag_verifier.py` (verbatim substring check + `>= 0.65` cosine similarity guard).
  2. Implement `graph/state.py`, `graph/nodes.py`, and `graph/workflow.py` using `langgraph` `StateGraph` + checkpointer.
  3. Expose `routers/tutor.py` (`POST /api/tutor/turn`, `GET /api/tutor/session/{id}/history`) and `routers/rag.py` (`POST /api/rag/upload`, `GET /api/rag/chapters`).
  4. Write `tests/test_socratic_graph_rag.py` verifying:
     - A mocked LLM that leaks the math answer on Attempt 1 is rejected by Step 2, routed to Step 3, and passes on Attempt 2.
     - A mocked LLM that fails 3 times triggers `circuit_breaker_node` at `iteration == 3`.
     - A hallucinated RAG quote not present in the source chunk is rejected by `rag_verifier.py`.
- **Verification Gate 3:** `pytest` passes 100% of Phase 0–3 tests. Log results in `AGENT_EXECUTION_LOG.md`. **STOP & WAIT FOR APPROVAL.**

### PHASE 4: React + Tailwind Frontend & Live Neuro-Symbolic Audit Drawer
- **Tasks:**
  1. Scaffold `frontend/` (Vite + React + TypeScript + Tailwind CSS).
  2. Create `src/types/api.ts` strictly matching `backend/app/schemas/`.
  3. Build `AuthModal.tsx` (Email/Password + Google login), `SubjectDashboard.tsx` (Track 1: Math, Track 2: Python/DSA, Track 3: Custom Textbook PDF Upload).
  4. Build the split-screen Tutor Workspace (`MathWorkspace.tsx` with KaTeX, `CodeWorkspace.tsx` with Monaco Editor, `RagWorkspace.tsx` with PDF source citations) paired with `NeuroSymbolicAuditDrawer.tsx` — a collapsible live inspector displaying each iteration of the 4-step Socratic loop, the model used, latency, and any symbolic rejections that occurred behind the scenes.
  5. Write `tests/test_e2e_api_contract.py` verifying OpenAPI schema alignment and full end-to-end user flow (Register -> Enroll -> Submit Turn -> Verify Audit Trail JSON).
- **Verification Gate 4:** Backend `pytest` passes 100% AND `npm run build` / `tsc --noEmit` in `frontend/` succeeds with zero TypeScript errors. Log results in `AGENT_EXECUTION_LOG.md`. **STOP & WAIT FOR APPROVAL.**

### PHASE 5: Dockerization, CI/CD & Cloud Run Deployment Readiness
- **Tasks:**
  1. Create a lightweight CPU-only multi-stage `Dockerfile` (`python:3.11-slim`, image size `< 350MB`, non-root user, serving on `$PORT` via `uvicorn`).
  2. Create `docker-compose.yml` for local full-stack spin-up.
  3. Create `.github/workflows/ci_cd.yml` running `pytest`, building the Docker container, pushing to Google Artifact Registry, and deploying to Google Cloud Run with `--min-instances=0 --max-instances=2 --memory=512Mi`.
  4. Generate a comprehensive `README.md` documenting architecture, budget math, and the complete Handoff Audit summary.
- **Verification Gate 5:** Full `pytest` suite passes, Docker build succeeds, and `AGENT_EXECUTION_LOG.md` + `VERIFICATION_GATES.md` are 100% finalized. **STOP & PRESENT FINAL HANDOFF REPORT.**