import time
import uuid
import logging
import csv
from io import StringIO
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.services.notifications import notify_case_users
from app.db.session import get_db
from app.db.session import SessionLocal
from app.models import AuditRecord, MissingPersonCase, ReferenceImage, Sighting, User
from app.models import CandidateMatch, SearchJob
from app.services.ai import (
    cosine_distance,
    decode_image,
    detect_faces,
    generate_reference_embedding,
    processing_signature,
    represent,
    validate_embedding,
)
from app.schemas import (
    CaseCreate,
    CaseResponse,
    CaseUpdate,
    DashboardResponse,
    CandidateReview,
    CandidateResponse,
    ImportSummary,
    MapRecord,
    SearchJobResponse,
    SightingResponse,
    SightingReview,
    LoginRequest,
    PublicSightingResponse,
    TokenResponse,
    UserCreate,
    UserResponse,
)

router = APIRouter(prefix="/api")
public_router = APIRouter(prefix="/api/public")
rate_buckets: dict[str, list[float]] = defaultdict(list)
logger = logging.getLogger(__name__)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = decode_access_token(authorization[7:])
        user_id = uuid.UUID(payload["sub"])
    except (ValueError, KeyError, TypeError, jwt.InvalidTokenError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User is inactive or unavailable")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


def audit(db: Session, user: User, action: str, entity_id: uuid.UUID | None = None) -> None:
    db.add(AuditRecord(
        user_id=user.id,
        action=action,
        entity_type=action.split(".", 1)[0],
        entity_id=entity_id,
    ))


async def store_image(upload: UploadFile) -> str:
    allowed = {"image/jpeg", "image/png", "image/webp"}
    if upload.content_type not in allowed:
        raise HTTPException(status_code=415, detail="Only JPEG, PNG, and WebP images are supported")
    content = await upload.read(settings.max_upload_size_bytes + 1)
    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=413, detail="Image exceeds the size limit")
    from io import BytesIO
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(BytesIO(content)) as image:
            image.verify()
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=415, detail="Uploaded file is not a valid image") from exc
    directory = Path(settings.upload_directory)
    directory.mkdir(parents=True, exist_ok=True)
    key = f"{uuid.uuid4()}.bin"
    (directory / key).write_bytes(content)
    return key


async def store_video(upload: UploadFile) -> str:
    allowed = {"video/mp4", "video/quicktime", "video/webm", "video/x-msvideo"}
    if upload.content_type not in allowed:
        raise HTTPException(status_code=415, detail="Only MP4, MOV, WebM, and AVI videos are supported")
    content = await upload.read(settings.max_video_size_bytes + 1)
    if len(content) > settings.max_video_size_bytes:
        raise HTTPException(status_code=413, detail="Video exceeds the size limit")
    key = f"{uuid.uuid4()}.video"
    directory = Path(settings.upload_directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / key).write_bytes(content)
    return key


def permitted_case(case: MissingPersonCase | None, user: User) -> bool:
    return case is not None and (user.role == "admin" or case.created_by_id == user.id)


def coordinate(value: float | None, minimum: float, maximum: float, name: str) -> float | None:
    if value is not None and not minimum <= value <= maximum:
        raise HTTPException(status_code=422, detail=f"{name} is outside its valid range")
    return value


def valid_references(references: list[ReferenceImage]) -> list[ReferenceImage]:
    valid: list[ReferenceImage] = []
    for reference in references:
        try:
            validate_embedding(reference.representation)
        except ValueError:
            logger.warning("Skipping invalid reference representation %s", reference.id)
            continue
        valid.append(reference)
    return valid


def process_image_job(job_id: uuid.UUID, content: bytes, query_storage_key: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(SearchJob, job_id)
        if job is None:
            return
        job.status, job.progress = "processing", 10
        db.commit()
        faces = detect_faces(decode_image(content))
        if not faces:
            job.status, job.progress = "completed", 100
            db.commit()
            return
        job.progress = 40
        references = valid_references(db.scalars(
            select(ReferenceImage).join(MissingPersonCase).where(
                ReferenceImage.case_id == job.case_id,
                ReferenceImage.representation.is_not(None),
            )
        ).all())
        if not references:
            raise ValueError("Search could not run because no valid reference embeddings are available.")
        matches_by_reference = {}
        valid_queries = 0
        for face in faces:
            try:
                query = represent(face.image)
            except ValueError as exc:
                logger.warning("Skipping face %s with invalid representation: %s", face.index, exc)
                continue
            valid_queries += 1
            for reference in references:
                distance = cosine_distance(query, reference.representation)
                if distance is not None and distance <= settings.face_match_distance_threshold:
                    previous = matches_by_reference.get(reference.id)
                    if previous is None or distance < previous[0]:
                        matches_by_reference[reference.id] = (distance, reference)
        if not valid_queries:
            raise ValueError("Search could not run because no valid face embeddings were generated.")
        matches = list(matches_by_reference.values())
        for distance, reference in sorted(matches, key=lambda value: value[0]):
            db.add(CandidateMatch(
                search_job_id=job.id, reference_image_id=reference.id,
                candidate_storage_key=reference.storage_key, distance=distance,
                status="unreviewed",
            ))
        job.status, job.progress = "completed", 100
        db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(SearchJob, job_id)
        if job:
            job.status, job.error_message = "failed", str(exc)
            db.commit()
    finally:
        Path(settings.upload_directory, query_storage_key).unlink(missing_ok=True)
        db.close()


def process_video_job(job_id: uuid.UUID, video_path: str) -> None:
    import cv2

    db = SessionLocal()
    job = db.get(SearchJob, job_id)
    capture = cv2.VideoCapture(video_path)
    try:
        if not capture.isOpened():
            raise ValueError("Video could not be opened")
        fps = capture.get(cv2.CAP_PROP_FPS) or 0
        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        duration = frame_count / fps if fps else 0
        if duration > settings.max_video_duration_seconds:
            raise ValueError("Video exceeds the duration limit")
        references = valid_references(db.scalars(
            select(ReferenceImage).join(MissingPersonCase).where(
                ReferenceImage.case_id == job.case_id,
                ReferenceImage.representation.is_not(None),
            )
        ).all())
        if not references:
            raise ValueError("Search could not run because no valid reference embeddings are available.")
        valid_queries = 0
        saw_face = False
        next_sample = 0.0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            timestamp = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if timestamp < next_sample:
                continue
            next_sample = timestamp + settings.video_frame_interval_seconds
            image = decode_image(cv2.imencode(".jpg", frame)[1].tobytes())
            faces = detect_faces(image)
            for face in faces:
                saw_face = True
                try:
                    query = represent(face.image)
                except ValueError as exc:
                    logger.warning("Skipping face %s with invalid representation: %s", face.index, exc)
                    continue
                valid_queries += 1
                for reference in references:
                    distance = cosine_distance(query, reference.representation)
                    if distance is not None and distance <= settings.face_match_distance_threshold:
                        db.add(CandidateMatch(
                            search_job_id=job.id, reference_image_id=reference.id,
                            candidate_storage_key=reference.storage_key, distance=distance,
                            frame_timestamp_seconds=timestamp, status="unreviewed",
                            source_storage_key=job.query_storage_key,
                        ))
            db.commit()
        if saw_face and not valid_queries:
            raise ValueError("Search could not run because no valid face embeddings were generated.")
        job.status, job.progress = "completed", 100
        db.commit()
    except Exception as exc:
        db.rollback()
        job = db.get(SearchJob, job_id)
        if job:
            job.status, job.error_message = "failed", str(exc)
            db.commit()
    finally:
        capture.release()
        Path(video_path).unlink(missing_ok=True)
        db.close()


@router.post("/auth/register", response_model=TokenResponse, status_code=201)
def register(payload: UserCreate, db: Session = Depends(get_db)) -> TokenResponse:
    if db.scalar(select(User).where(User.email == payload.email.lower())):
        raise HTTPException(status_code=409, detail="Email is already registered")
    has_users = db.scalar(select(func.count(User.id))) or 0
    role = "admin" if has_users == 0 else "authorized_user"
    user = User(email=payload.email.lower(), password_hash=hash_password(payload.password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenResponse(access_token=create_access_token(str(user.id), user.role), user=user)


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenResponse(access_token=create_access_token(str(user.id), user.role), user=user)


@router.get("/auth/me", response_model=UserResponse)
def me(user: User = Depends(current_user)) -> User:
    return user


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)) -> DashboardResponse:
    base = select(MissingPersonCase)
    if user.role != "admin":
        base = base.where(MissingPersonCase.created_by_id == user.id)
    cases = list(db.scalars(base.order_by(MissingPersonCase.updated_at.desc())))
    counts = {status_name: sum(case.status == status_name for case in cases) for status_name in ("open", "under_review", "resolved")}
    return DashboardResponse(
        total_cases=len(cases), open_cases=counts["open"], under_review_cases=counts["under_review"],
        resolved_cases=counts["resolved"],
        recent_activity=[{"id": str(case.id), "name": case.name, "status": case.status, "updated_at": case.updated_at} for case in cases[:5]],
    )


@router.get("/dashboard/map", response_model=list[MapRecord])
def dashboard_map(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[MapRecord]:
    case_query = select(MissingPersonCase)
    if user.role != "admin":
        case_query = case_query.where(MissingPersonCase.created_by_id == user.id)
    records: list[MapRecord] = []
    cases = db.scalars(case_query).all()
    allowed_case_ids = {case.id for case in cases}
    for case in cases:
        if case.last_seen_latitude is not None and case.last_seen_longitude is not None:
            records.append(MapRecord(
                id=case.id, record_type="case", latitude=case.last_seen_latitude,
                longitude=case.last_seen_longitude, label=case.name, status=case.status,
            ))
    sightings = db.scalars(select(Sighting).where(Sighting.case_id.in_(allowed_case_ids))).all() if allowed_case_ids else []
    for sighting in sightings:
        if sighting.latitude is not None and sighting.longitude is not None:
            records.append(MapRecord(
                id=sighting.id, record_type="sighting", latitude=sighting.latitude,
                longitude=sighting.longitude, label="Reported sighting", status=sighting.status,
                observed_at=sighting.observed_at,
            ))
    return records


@router.get("/admin/notification-status")
def notification_status(user: User = Depends(require_admin)) -> dict[str, bool]:
    return {"smtp_configured": bool(settings.smtp_host and settings.smtp_sender)}


@router.post("/admin/demo-import", response_model=ImportSummary)
async def import_demo_data(
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ImportSummary:
    if file.content_type not in {"text/csv", "application/csv", "application/vnd.ms-excel"}:
        raise HTTPException(status_code=415, detail="Upload a CSV file")
    content = await file.read(settings.max_import_size_bytes + 1)
    if len(content) > settings.max_import_size_bytes:
        raise HTTPException(status_code=413, detail="CSV exceeds the size limit")
    required = {"case_key", "name", "status"}
    try:
        reader = csv.DictReader(StringIO(content.decode("utf-8-sig")))
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="CSV must be UTF-8 encoded") from exc
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise HTTPException(status_code=422, detail=f"CSV requires columns: {', '.join(sorted(required))}")
    errors: list[str] = []
    imported_cases = imported_sightings = rejected = 0
    try:
        for row_number, row in enumerate(reader, 2):
            try:
                case_key, name, status_value = row["case_key"].strip(), row["name"].strip(), row["status"].strip()
                if not case_key or not name or status_value not in {"open", "under_review", "resolved", "closed"}:
                    raise ValueError("case_key, name, and a valid status are required")
                if db.scalar(select(MissingPersonCase).where(MissingPersonCase.external_id == case_key)):
                    raise ValueError("duplicate case_key")
                case = MissingPersonCase(
                    external_id=case_key, name=name, status=status_value,
                    description=f"Synthetic demo record: {row.get('description', '').strip()}",
                    created_by_id=user.id,
                    last_seen_location=row.get("last_seen_location") or None,
                    last_seen_latitude=float(row["last_seen_latitude"]) if row.get("last_seen_latitude") else None,
                    last_seen_longitude=float(row["last_seen_longitude"]) if row.get("last_seen_longitude") else None,
                )
                if row.get("last_seen_at"):
                    case.last_seen_at = datetime.fromisoformat(row["last_seen_at"])
                coordinate(case.last_seen_latitude, -90, 90, "last_seen_latitude")
                coordinate(case.last_seen_longitude, -180, 180, "last_seen_longitude")
                db.add(case)
                db.flush()
                imported_cases += 1
                if row.get("sighting_key"):
                    sighting_key = row["sighting_key"].strip()
                    if db.scalar(select(Sighting).where(Sighting.external_id == sighting_key)):
                        raise ValueError("duplicate sighting_key")
                    sighting = Sighting(
                        external_id=sighting_key, case_id=case.id,
                        source="synthetic_demo", status="pending_review",
                        location=row.get("sighting_location") or None,
                        latitude=float(row["sighting_latitude"]) if row.get("sighting_latitude") else None,
                        longitude=float(row["sighting_longitude"]) if row.get("sighting_longitude") else None,
                        notes="Synthetic demo record",
                    )
                    if row.get("observed_at"):
                        sighting.observed_at = datetime.fromisoformat(row["observed_at"])
                    coordinate(sighting.latitude, -90, 90, "sighting_latitude")
                    coordinate(sighting.longitude, -180, 180, "sighting_longitude")
                    db.add(sighting)
                    imported_sightings += 1
            except (KeyError, TypeError, ValueError) as exc:
                rejected += 1
                errors.append(f"row {row_number}: {exc}")
        if errors:
            db.rollback()
            return ImportSummary(imported_cases=0, imported_sightings=0, rejected_rows=rejected, errors=errors)
        audit(db, user, "demo_data.imported")
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=422, detail="Import failed; no rows were committed")
    return ImportSummary(imported_cases=imported_cases, imported_sightings=imported_sightings, rejected_rows=0, errors=[])


@router.get("/cases", response_model=list[CaseResponse])
def list_cases(
    search: str | None = None, status_filter: str | None = None,
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[MissingPersonCase]:
    query = select(MissingPersonCase)
    if user.role != "admin":
        query = query.where(MissingPersonCase.created_by_id == user.id)
    if search:
        query = query.where(or_(MissingPersonCase.name.ilike(f"%{search}%"), MissingPersonCase.description.ilike(f"%{search}%")))
    if status_filter:
        query = query.where(MissingPersonCase.status == status_filter)
    return list(db.scalars(query.order_by(MissingPersonCase.created_at.desc())))


@router.post("/cases", response_model=CaseResponse, status_code=201)
def create_case(payload: CaseCreate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> MissingPersonCase:
    case = MissingPersonCase(**payload.model_dump(), created_by_id=user.id)
    db.add(case)
    db.flush()
    audit(db, user, "case.created", case.id)
    db.commit()
    db.refresh(case)
    return case


@router.get("/cases/{case_id}", response_model=CaseResponse)
def get_case(case_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> MissingPersonCase:
    case = db.get(MissingPersonCase, case_id)
    if case is None or (user.role != "admin" and case.created_by_id != user.id):
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.get("/sightings", response_model=list[SightingResponse])
def list_sightings(
    status_filter: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[Sighting]:
    query = select(Sighting).join(MissingPersonCase)
    if user.role != "admin":
        query = query.where(MissingPersonCase.created_by_id == user.id)
    if status_filter:
        query = query.where(Sighting.status == status_filter)
    return list(db.scalars(query.order_by(Sighting.created_at.desc())))


@router.patch("/sightings/{sighting_id}", response_model=SightingResponse)
def review_sighting(
    sighting_id: uuid.UUID,
    payload: SightingReview,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Sighting:
    sighting = db.get(Sighting, sighting_id)
    if sighting is None or not permitted_case(sighting.case, user):
        raise HTTPException(status_code=404, detail="Sighting not found")
    sighting.status = payload.status
    audit(db, user, f"sighting.{payload.status}", sighting.id)
    db.commit()
    db.refresh(sighting)
    return sighting


@router.patch("/cases/{case_id}", response_model=CaseResponse)
def update_case(case_id: uuid.UUID, payload: CaseUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)) -> MissingPersonCase:
    case = db.get(MissingPersonCase, case_id)
    if case is None or (user.role != "admin" and case.created_by_id != user.id):
        raise HTTPException(status_code=404, detail="Case not found")
    for key, value in payload.model_dump().items():
        setattr(case, key, value)
    audit(db, user, "case.updated", case.id)
    db.commit()
    db.refresh(case)
    return case


@router.post("/cases/{case_id}/images", response_model=dict, status_code=201)
async def upload_reference_image(case_id: uuid.UUID, image: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)) -> dict:
    case = db.get(MissingPersonCase, case_id)
    if case is None or (user.role != "admin" and case.created_by_id != user.id):
        raise HTTPException(status_code=404, detail="Case not found")
    key = await store_image(image)
    record = ReferenceImage(
        case_id=case_id, storage_key=key, processing_signature=processing_signature()
    )
    try:
        content = (Path(settings.upload_directory) / key).read_bytes()
        record.representation = generate_reference_embedding(content)
    except Exception as exc:
        logger.warning("Reference representation unavailable for %s: %s", record.id, exc)
        record.representation = None
    db.add(record)
    audit(db, user, "reference_image.uploaded", case_id)
    db.commit()
    db.refresh(record)
    return {"id": str(record.id), "created_at": record.created_at}


@router.post("/admin/rebuild-embeddings")
def rebuild_embeddings(
    case_id: uuid.UUID | None = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    query = select(ReferenceImage)
    if case_id is not None:
        query = query.where(ReferenceImage.case_id == case_id)
    records = db.scalars(query.order_by(ReferenceImage.created_at)).all()
    regenerated = failed = 0
    errors: list[str] = []
    for record in records:
        try:
            content = (Path(settings.upload_directory) / record.storage_key).read_bytes()
            record.representation = generate_reference_embedding(content)
            record.processing_signature = processing_signature()
            regenerated += 1
        except (OSError, ValueError) as exc:
            record.representation = None
            failed += 1
            errors.append(f"{record.id}: {exc}")
            logger.warning("Reference representation regeneration failed for %s: %s", record.id, exc)
    audit(db, user, "reference_embeddings.rebuilt", case_id)
    db.commit()
    return {"examined": len(records), "regenerated": regenerated, "failed": failed, "errors": errors}


@router.get("/images/{image_id}")
def get_reference_image(image_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> FileResponse:
    image = db.get(ReferenceImage, image_id)
    if image is None or (user.role != "admin" and image.case.created_by_id != user.id):
        raise HTTPException(status_code=404, detail="Image not found")
    path = Path(settings.upload_directory) / image.storage_key
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Image file not found")
    return FileResponse(path, media_type="application/octet-stream")


@router.delete("/images/{image_id}", status_code=204)
def delete_reference_image(image_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> None:
    image = db.get(ReferenceImage, image_id)
    if image is None or (user.role != "admin" and image.case.created_by_id != user.id):
        raise HTTPException(status_code=404, detail="Image not found")
    path = Path(settings.upload_directory) / image.storage_key
    if path.is_file():
        path.unlink()
    audit(db, user, "reference_image.deleted", image.case_id)
    db.delete(image)
    db.commit()


@public_router.post("/sightings", response_model=PublicSightingResponse, status_code=201)
async def submit_sighting(
    request: Request, case_id: uuid.UUID = Form(...), observed_at: datetime = Form(...),
    location: str = Form(...), description: str | None = Form(None),
    latitude: float | None = Form(None), longitude: float | None = Form(None),
    image: UploadFile = File(...), db: Session = Depends(get_db),
) -> PublicSightingResponse:
    now = time.time()
    client = request.client.host if request.client else "unknown"
    rate_buckets[client] = [value for value in rate_buckets[client] if now - value < 60]
    if len(rate_buckets[client]) >= settings.rate_limit_per_minute:
        raise HTTPException(status_code=429, detail="Too many submissions; try again later")
    rate_buckets[client].append(now)
    case = db.get(MissingPersonCase, case_id)
    if case is None or case.status in {"resolved", "closed"}:
        raise HTTPException(status_code=404, detail="Case is not accepting sightings")
    coordinate(latitude, -90, 90, "latitude")
    coordinate(longitude, -180, 180, "longitude")
    key = await store_image(image)
    sighting = Sighting(case_id=case_id, source="public_portal", storage_key=key, observed_at=observed_at, location=location, notes=description, latitude=latitude, longitude=longitude)
    db.add(sighting)
    db.commit()
    notify_case_users(db, case, "New sighting submitted", "A new public sighting was submitted and is awaiting authorized review.")
    return PublicSightingResponse(id=sighting.id, status=sighting.status, message="Sighting submitted for review")


@router.post("/cases/{case_id}/search/image", response_model=SearchJobResponse, status_code=202)
async def search_image(
    case_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    image: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SearchJob:
    case = db.get(MissingPersonCase, case_id)
    if not permitted_case(case, user):
        raise HTTPException(status_code=404, detail="Case not found")
    content = await image.read(settings.max_upload_size_bytes + 1)
    if len(content) > settings.max_upload_size_bytes:
        raise HTTPException(status_code=413, detail="Image exceeds the size limit")
    try:
        decode_image(content)
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    key = f"{uuid.uuid4()}.search"
    Path(settings.upload_directory).mkdir(parents=True, exist_ok=True)
    (Path(settings.upload_directory) / key).write_bytes(content)
    job = SearchJob(case_id=case_id, job_type="image", status="queued", query_storage_key=key)
    db.add(job)
    audit(db, user, "search.image.created", case_id)
    db.commit()
    db.refresh(job)
    background_tasks.add_task(process_image_job, job.id, content, key)
    return job


@router.post("/cases/{case_id}/search/video", response_model=SearchJobResponse, status_code=202)
async def search_video(
    case_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> SearchJob:
    case = db.get(MissingPersonCase, case_id)
    if not permitted_case(case, user):
        raise HTTPException(status_code=404, detail="Case not found")
    key = await store_video(video)
    job = SearchJob(case_id=case_id, job_type="video", status="queued", query_storage_key=key)
    db.add(job)
    audit(db, user, "search.video.created", case_id)
    db.commit()
    db.refresh(job)
    background_tasks.add_task(
        process_video_job, job.id, str(Path(settings.upload_directory) / key)
    )
    return job


@router.get("/search-jobs/{job_id}", response_model=SearchJobResponse)
def get_search_job(
    job_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> SearchJob:
    job = db.scalar(
        select(SearchJob).options(
            selectinload(SearchJob.candidate_matches),
            selectinload(SearchJob.case),
        ).where(SearchJob.id == job_id)
    )
    if job is None or not permitted_case(job.case, user):
        raise HTTPException(status_code=404, detail="Search job not found")
    return job


@router.get("/search-jobs", response_model=list[SearchJobResponse])
def list_search_jobs(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[SearchJob]:
    query = select(SearchJob).options(
        selectinload(SearchJob.candidate_matches),
        selectinload(SearchJob.case),
    ).join(MissingPersonCase)
    if user.role != "admin":
        query = query.where(MissingPersonCase.created_by_id == user.id)
    return list(db.scalars(query.order_by(SearchJob.created_at.desc())))


@router.patch("/candidate-matches/{candidate_id}", response_model=CandidateResponse)
def review_candidate(
    candidate_id: uuid.UUID,
    payload: CandidateReview,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> CandidateMatch:
    candidate = db.get(CandidateMatch, candidate_id)
    if candidate is None or not permitted_case(candidate.search_job.case, user):
        raise HTTPException(status_code=404, detail="Candidate match not found")
    candidate.status = payload.status
    audit(db, user, f"candidate.{payload.status}", candidate.id)
    db.commit()
    db.refresh(candidate)
    return candidate
