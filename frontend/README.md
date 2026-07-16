# SYN-City Dashboard

Simple React replay dashboard for the backend. It shows KPI history, the Stage-1
P10-P90 envelope band when available, and the live decision feed.

## Setup

```powershell
cd frontend
pnpm install
```

## Run

Start the backend on port 8000 first:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --port 8000
```

Then start the frontend on port 5173:

```powershell
cd frontend
pnpm run dev
```

The frontend reads `VITE_BACKEND_URL` and defaults to `http://localhost:8000`.
