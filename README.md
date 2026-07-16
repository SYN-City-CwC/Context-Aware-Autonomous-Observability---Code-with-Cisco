# SYN-City

SYN-City is a deterministic observability demo for match-night traffic: it learns context-conditioned KPI envelopes, suppresses expected event traffic, detects unexplained credential stuffing and checkout-path faults, then shows a simulated response and RCA in one replay dashboard.

## Run

Backend (from `backend`): activate `.venv`, run `python -m app.train` if `models/` is absent, then `uvicorn app.main:app --reload`. Frontend (from `frontend`): run `pnpm install` then `pnpm dev`.

The replay shows a context-aware M-217 suppression, credential stuffing with an 80% simulated edge rate-limit, a SYN flood, traffic-independent memory leak, telemetry silence, and a checkout retry storm. Attack discrimination fuses source entropy, flow similarity, machine-regular timing, auth failures, and crowd coherence; fault discrimination fuses retry amplification, memory slope, and deploy correlation. Stage 4 ships a deterministic CPU torch LSTM autoencoder plus Isolation Forest/POT scoring and a liveness guard. RCA narratives use Groq -> Gemini -> rules when keys are present in `backend/.env`, and degrade gracefully to rules without them. Current detector mode is `DETECTOR=envelope` (set `DETECTOR=rules` for degraded mode).

```mermaid
flowchart LR
  T[Plane 0: Telemetry simulator] --> C[Plane 1: Event context]
  C --> D[Plane 2: Envelope detector]
  D --> R[Plane 3: Rule RCA]
  D --> A[Plane 4: Rate-limit action]
  A --> T
  R --> U[Plane 5: Dashboard]
  A --> U
```

## Not yet built

- Full action machinery and automated regression tests.
