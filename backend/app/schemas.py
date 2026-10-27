from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class CaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    date_of_birth: date | None = None
    last_seen_location: str | None = Field(default=None, max_length=255)
    last_seen_at: datetime | None = None
    last_seen_latitude: float | None = Field(default=None, ge=-90, le=90)
    last_seen_longitude: float | None = Field(default=None, ge=-180, le=180)


class CaseUpdate(CaseCreate):
    status: str = Field(default="open", pattern="^(open|under_review|resolved|closed)$")


class MapRecord(BaseModel):
    id: UUID
    record_type: str
    latitude: float
    longitude: float
    label: str
    status: str
    observed_at: datetime | None = None


class ImportSummary(BaseModel):
    imported_cases: int
    imported_sightings: int
    rejected_rows: int
    errors: list[str]


class ReferenceImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime


class CaseResponse(CaseCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: str
    created_by_id: UUID
    created_at: datetime
    updated_at: datetime
    reference_images: list[ReferenceImageResponse] = []


class DashboardResponse(BaseModel):
    total_cases: int
    open_cases: int
    under_review_cases: int
    resolved_cases: int
    recent_activity: list[dict]


class CandidateResponse(BaseModel):
    id: UUID
    case_id: UUID
    status: str
    distance: float | None
    frame_timestamp_seconds: float | None
    source_storage_key: str | None
    created_at: datetime


class SearchJobResponse(BaseModel):
    id: UUID
    case_id: UUID
    job_type: str
    status: str
    progress: int
    error_message: str | None
    created_at: datetime
    candidates: list[CandidateResponse] = []


class CandidateReview(BaseModel):
    status: str = Field(pattern="^(under_review|possible_match|not_a_match)$")


class PublicSightingResponse(BaseModel):
    id: UUID
    status: str
    message: str
