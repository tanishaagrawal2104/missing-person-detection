from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from app.models import (  # noqa: E402,F401
    AuditRecord,
    CandidateMatch,
    MissingPersonCase,
    ReferenceImage,
    SearchJob,
    Sighting,
    User,
)
