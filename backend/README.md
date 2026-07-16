# SYN-City Stage 0 Backend

Stage 0 provides a deterministic match-night simulator, a rule-based context detector, a
terminal demo, and a FastAPI replay API.

## Setup (PowerShell)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run the API

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --port 8000
```

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

`scenarios/the-final.json` uses ISO-8601 UTC timestamps ending in `Z` for every time
field. The scenario loader rejects local shorthand times so alternate scenarios remain
unambiguous.
