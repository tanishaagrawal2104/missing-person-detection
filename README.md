# Missing Person Detection

Missing-person detection platform using **YOLOv8** for face detection and
**DeepFace** for facial recognition. AI search results are always subject to
authorized human review.

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

## AI processing (Chunk 3)

Install the AI dependencies from `backend/requirements.txt`, download a
YOLOv8-compatible face detector weight file separately, and set
`FACE_DETECTOR_WEIGHTS` to its path. Standard COCO YOLO weights are not a
face detector and are not suitable here. DeepFace uses the configured
`DEEPFACE_MODEL_NAME` and cosine-distance threshold; its model assets may be
downloaded by DeepFace on first use, depending on the selected model.

After configuring PostgreSQL and the AI settings:

```powershell
cd backend
alembic upgrade head
uvicorn app.main:app --reload
```

Image searches are queued as jobs and video searches run in FastAPI background
tasks. Search results are possible matches only and require authorized human
review. Video processing requires OpenCV-compatible codecs and does not
provide a durable external worker queue; a process restart stops in-flight
background jobs.