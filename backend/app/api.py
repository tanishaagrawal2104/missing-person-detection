import time
import uuid
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import jwt
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.session import get_db
from app.models import AuditRecord, MissingPersonCase, ReferenceImage, Sighting, User
from app.schemas import (
    CaseCreate,
    CaseResponse,
    CaseUpdate,
    DashboardResponse,
    LoginRequest,
    PublicSightingResponse,
    TokenResponse,
    UserCreate,
    UserResponse,
)

router = APIRouter(prefix="/api")
public_router = APIRouter(prefix="/api/public")
rate_buckets: dict[str, list[float]] = defaultdict(list)


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
    db.add(AuditRecord(user_id=user.id, action=action, entity_type="case", entity_id=entity_id))


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
    record = ReferenceImage(case_id=case_id, storage_key=key)
    db.add(record)
    audit(db, user, "reference_image.uploaded", case_id)
    db.commit()
    db.refresh(record)
    return {"id": str(record.id), "created_at": record.created_at}


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
    key = await store_image(image)
    sighting = Sighting(case_id=case_id, source="public_portal", storage_key=key, observed_at=observed_at, location=location, notes=description)
    db.add(sighting)
    db.commit()
    return PublicSightingResponse(id=sighting.id, status=sighting.status, message="Sighting submitted for review")
