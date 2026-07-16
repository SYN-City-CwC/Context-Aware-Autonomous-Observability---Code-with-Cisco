# SYN-City Stage 0 Dashboard

Simple React replay dashboard for the Stage 0 backend.

## Setup

```powershell
cd frontend
npm install
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
npm run dev
```

The frontend reads `VITE_BACKEND_URL` and defaults to `http://localhost:8000`.
