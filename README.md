# SHAKIB AI

**Unified Deep Research & All-in-One Agent** — one web application that combines:

- **open-agent** (MIT) — the main agent, used as an internal tool/browser/computer-use service
- **new-api** (AGPL-3.0) — the central model gateway: every model call goes through it
- **gpt-researcher** (Apache-2.0) — the deep-research engine, embedded as a Python library

Planned capabilities: AI chat, multi-agent deep research with citations,
source-credibility assessment and contradiction detection, a Critical
Thinking Council (Devil's Advocate, Autopsy, Red Team, Expose), Bengali and
English reports with PDF/DOCX/Markdown export, file & PDF reader, long-term
memory, voice assistant, image generation, skills/tools, history, settings
and user authentication.

See the architecture & integration plan in the project workspace for the full
design, and [NOTICE.md](NOTICE.md) for upstream licenses.

## Architecture (summary)

```
Browser → SHAKIB AI Web (React + TS) → SHAKIB AI Core (FastAPI, Python 3.12)
Core ──► new-api gateway (/v1) ──► upstream model providers (user's own keys)
Core ──► open-agent service (agent/tool tasks)
Data: PostgreSQL (two databases: shakib_core, new_api) · Redis
```

Key rules baked into the design:

- The browser talks **only** to Core. Gateway keys live server-side in Core
  and never reach frontend code.
- new-api runs **unmodified** as its own container (AGPL-3.0 — see NOTICE.md);
  SHAKIB AI is an open-source project.
- No provider is assumed free or unlimited; every external key is the user's
  own, entered server-side.

## Current status: BACKEND + FRONTEND IMPLEMENTED

What exists now is the working application (backend + unified frontend);
live model features still need a running gateway and the user's own keys:

- ✅ `docker-compose.yml` — gateway / postgres / redis / core / web services
- ✅ `services/core` — FastAPI app that boots; `GET /health` returns real
  status; chat, settings, research, council, auth, conversations, memory,
  user key storage, the file/PDF reader, image generation and the skills
  registry are implemented (below); only the settings index endpoint still
  returns an honest **501 Not Implemented**
- ✅ `apps/web` — the **unified frontend is implemented**: Vite + React + TS
  app with sidebar navigation (mobile-collapsible) and ten working views —
  Chat (role select fast/smart/strategic, Markdown replies, saved
  conversations), Deep Research (en/বাংলা, credibility-badged sources,
  contradiction status, MD/DOCX/PDF export downloads, "Run Council"
  shortcut), Critical Analysis (run_id or pasted report; the four Council
  members as cards, member errors shown honestly), Files (drag/picker
  upload, extracted-text viewer), Images (gateway passthrough, URL or
  base64), Memory, Skills (live readiness badges), History, Settings
  (read-only model-role chains + write-only provider key manager showing
  masked last4 only) and Account (register/login, JWT in localStorage,
  guest/dev mode when signed out). Voice is the browser Web Speech API:
  dictation into chat/research inputs and read-aloud for replies/reports
  (en-US / bn-BD). Every view reads the real Core API — backend 503
  "not configured" details are shown verbatim, never replaced with fake
  data. `npm run build` passes (tsc + Vite); the dev server was
  smoke-tested against a live Core (health, skills, files, and the
  authenticated memory/conversations/keys flows all verified end-to-end;
  chat/research/images returned their honest 503s without keys).
  **CORS:** Core sends CORS headers via `CORSMiddleware` for the origins
  in `CORS_ORIGINS` (default `http://localhost:5173,http://127.0.0.1:5173`,
  the Vite dev server). **Production must set `CORS_ORIGINS` to the exact
  deployed web origin(s)** — never `*`, because requests carry the
  Authorization header. The Vite dev-server proxy in `vite.config.ts`
  remains available as an alternative for local dev.
- ✅ **Model gateway client** (`services/core/app/gateway.py`) — async
  OpenAI-compatible client for the new-api gateway with per-role model
  fallback chains (`MODEL_FAST` / `MODEL_SMART` / `MODEL_STRATEGIC` /
  `MODEL_EMBEDDING`, comma-separated, tried in order on HTTP 429/5xx or
  connection errors). Wired into `POST /api/chat/`, `GET /api/chat/models`
  and `GET /api/settings/models`. **Mock-tested only** (httpx MockTransport,
  14 tests passing): with no gateway key configured the chat endpoint
  answers an honest **503 "model gateway not configured"** — no fake
  replies. A live test against a running new-api with a real upstream key
  is still pending.
- ✅ **Deep research module** (`services/core/app/research/`) — gpt-researcher
  **0.17.0** embedded as a library via `ResearchService`, configured to talk
  to the gateway (`OPENAI_BASE_URL` = gateway `/v1`, role models from the
  `MODEL_*` chains, `RETRIEVER` + optional Tavily key; key-free retrievers
  duckduckgo/arxiv/openalex supported). Runs are stored under
  `services/core/data/reports/<run_id>/` (report.md, sources.json,
  meta.json). Plus: deterministic **credibility scoring** (domain/HTTPS/
  corroboration heuristics — signals, not truth checks), an LLM
  **contradiction check** over extracted claims (reports its own
  ok/skipped/error status), and **MD/DOCX/PDF export** — PDF via WeasyPrint,
  which *refuses* to run when no Bengali-capable font is present (Noto Sans
  Bengali is installed on the dev box; a Bengali PDF was rendered and
  visually verified). Bengali reports: gpt-researcher 0.17.0 has no language
  parameter (verified in the installed package), so Bengali is requested via
  an instruction appended to the query and recorded in meta.json.
  **Mock-tested only** (fake researcher + fake gateway, 19 research tests):
  `POST /api/research/` answers an honest **503**
  naming the missing env until gateway + retriever are configured. A live
  end-to-end research run still needs the user's gateway/Tavily keys.
- ✅ **Critical Thinking Council** (`services/core/app/council.py`) — four
  adversarial passes over a report + its sources, each a separate gateway
  call with its own system prompt and strict JSON schema: **Devil's
  Advocate** (strongest counter-arguments), **Autopsy** (weakest reasoning
  steps / thinnest evidence), **Red Team** (how the conclusion could be
  wrong, manipulated or gamed) and **Expose** (missing angles, one-sided
  sourcing, undisclosed limitations). Uses the `strategic` model role with
  `smart` as fallback; Bengali output on request. The result is a
  **separate analysis** — stored as `council.json` beside the research run
  when a `run_id` is given — and never modifies the report (a test asserts
  `report.md` is byte-identical after a council run). A member whose reply
  is not valid schema JSON is retried once, then reported as an `error`
  section — never fabricated. `POST /api/council/` accepts `{run_id}` or
  an inline `{report_markdown, sources}`; unknown run → **404**, gateway
  unconfigured → **503**. **Mock-tested only** (fake gateway, 10 council
  tests; full suite 43 passing). A live council run still needs the user's
  gateway key.
- ✅ **Secure storage + authentication** (`services/core/app/db.py`,
  `app/models.py`, `app/security.py`) — SQLAlchemy 2.x over `DATABASE_URL`
  (dev default: local SQLite file; compose provides PostgreSQL in prod).
  Tables: users, conversations, messages, memory_items, user_api_keys.
  Passwords are **bcrypt**-hashed; sessions are **24h JWTs** (HS256,
  `JWT_SECRET`). Endpoints: `POST /api/auth/register` (201 + token; 409 on
  duplicate email), `POST /api/auth/login` (401 on bad credentials),
  `GET /api/auth/me`; per-user **conversations** CRUD + messages and
  **memory** CRUD — every query is scoped to the token's user and another
  user's object returns **404** (existence is not leaked). Users can store
  their own provider API keys via `POST/GET/DELETE /api/settings/keys`:
  keys are **Fernet-encrypted at rest** (`ENCRYPTION_KEY`) and the API only
  ever returns provider + last4 + created_at — never the key. If
  `ENCRYPTION_KEY` is unset the Fernet key is derived from `JWT_SECRET`
  (SHA-256) — a **dev convenience only**; production must set
  `ENCRYPTION_KEY`, because rotating `JWT_SECRET` would otherwise orphan
  stored keys. `AUTH_REQUIRED` (default false): when true, chat/research/
  council reject unauthenticated calls with **401**. **13 tests**
  (`tests/test_auth_storage.py`, temp SQLite) cover the full flows
  including ciphertext-at-rest and cross-user isolation; full suite
  **56 passing**.
- ✅ **File & PDF reader** (`services/core/app/files_service.py`,
  `app/routers/files.py`) — `POST /api/files/upload` (multipart) accepts
  **.pdf / .txt / .md / .docx** only (**415** otherwise), caps uploads at
  **20 MB** (**413** above, enforced while reading), stores the bytes under
  `services/core/data/uploads/<scope>/<id>` (scope = owner user id, or
  `anon`) and extracts text at upload time — **pypdf** for PDF,
  **python-docx** for DOCX, UTF-8 for text — into the new `documents`
  table. `GET /api/files/{id}` serves metadata + text (truncated at 50k
  chars with a `truncated` flag), `GET /api/files/` lists metadata only,
  `DELETE` removes row + bytes. Scoping matches conversations: another
  scope's document is **404**, and a present-but-invalid token is **401**,
  never a silent downgrade to anon. A corrupt PDF answers **422** with a
  plain message (no stack trace). **Mock/DB-tested only** (13 tests in
  `tests/test_files_images_skills.py`, incl. a WeasyPrint-built PDF whose
  English **and Bengali** text round-trips through extraction).
- ✅ **Image generation** (`app/routers/images.py`,
  `GatewayClient.generate_image`) — `POST /api/images/generate`
  `{prompt, model?, size?}` calls the gateway's
  `POST /v1/images/generations` and passes its payload through unchanged;
  the model defaults to the first entry of the `MODEL_SMART` chain. Same
  honesty contract as chat: **503** while the gateway is unconfigured,
  **502** on gateway errors. **Mock-tested only** (httpx MockTransport) —
  no live image has been generated; that needs a running gateway with an
  image-capable upstream model.
- ✅ **Skills registry** (`app/routers/skills.py`) — `GET /api/skills/`
  lists the built-in capabilities (deep_research, critical_council,
  file_reader, image_generation, long_term_memory, voice) with a status
  computed from the *same* settings flags the endpoints check:
  `ready`, `needs_configuration` (with the exact missing env names), or
  `client_side` for the browser-speech voice assistant. Tests assert the
  statuses flip when the gateway/retriever configuration appears.
- ✅ Core tests (`services/core/tests/` — health + gateway + research +
  council + auth/storage + files/images/skills + **security** suites;
  **95 passing**). The security suite covers JWT forgery/expiry,
  cross-user isolation, upload abuse, injection, AUTH_REQUIRED
  enforcement, CORS and secret-leakage scans; a live golden-path check
  (`tests/integration_live.py`, real uvicorn boot) passes 16/16 steps,
  with chat returning its honest 503 while no gateway is configured.

**NOT built yet:** live gateway/research/council/image verification (needs
a running new-api plus the user's own upstream and Tavily keys);
deployment. Nothing in this repo should be read as a working feature until
its module lands with tests.

## Run the scaffold

With Docker:

```bash
cp .env.example .env   # fill in values for local dev
docker compose up --build
# web → http://localhost:5173 · core health → http://localhost:8000/health
```

Without Docker (Core only):

```bash
cd services/core
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -v
.venv/bin/uvicorn app.main:app --port 8000
```

Web only:

```bash
cd apps/web
npm install
npm run dev        # or: npm run build
```

## Licenses

This project's own code will be published under an open-source license
compatible with its components. Upstream components keep their own licenses —
MIT (open-agent), Apache-2.0 (gpt-researcher), AGPL-3.0 (new-api). See
[NOTICE.md](NOTICE.md).
