# SYN-City Backend

The backend provides a deterministic match-night simulator, a LightGBM
context-conditioned envelope detector, a rule-based degraded detector, a terminal demo,
and a FastAPI replay API.

## Setup (PowerShell)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Train the envelope models

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.train
```

Training generates 14 three-hour sim windows, fits one LightGBM P10/P50/P90 quantile
envelope per KPI plus a context-blind P90 twin, writes model files to `backend/models/`,
and prints per-KPI validation coverage. Expected runtime is about one minute on this
machine.

## Run the API

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --port 8000
```

`DETECTOR=envelope` is the default and requires `python -m app.train` first. Use
`$env:DETECTOR="rules"` before `uvicorn` or `python -m app.demo` to run the Stage-0
rule detector degraded mode.

## Run the terminal demo

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.demo
```

## Run tests

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest
```

## Scenario timestamp convention

`scenarios/the-final.json` uses ISO-8601 UTC timestamps ending in `Z` for match-night
fields. Prior-history events use `day_offset` plus HH:MM time-of-day strings. KPI
`diurnal` applies a smooth daily multiplier with a trough near 04:00 and peak near 20:00.
