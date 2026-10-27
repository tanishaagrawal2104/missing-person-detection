# Missing Person Detection

Foundation for a missing-person detection platform using **YOLOv8** for object
detection and **DeepFace** for facial recognition. The AI pipeline and product
workflows are intentionally not implemented yet.

## Architecture

- `frontend/`: React + Vite dashboard shell.
- `backend/`: FastAPI application, configuration, SQLAlchemy models, and
  Alembic migrations.
- PostgreSQL stores users, cases, images, sightings, search jobs, candidate
  matches, and audit records. Uploaded media and model weights are kept outside
  version control.

## Prerequisites

- Node.js 20+
- Python 3.11+
- PostgreSQL 15+

## Setup

1. Copy `backend/.env.example` to `backend/.env` and set
   `DATABASE_URL` to a local PostgreSQL database.
2. Create a Python environment and install backend dependencies:

   ```powershell
   cd backend
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Initialize the database:

   ```powershell
   alembic upgrade head
   ```

4. Run the API:

   ```powershell
   uvicorn app.main:app --reload
   ```

5. In another terminal, install and run the frontend:

   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

The API health check is available at `http://localhost:8000/health` and the
frontend at the Vite URL shown in the terminal.