"""Add case details and sighting metadata.

Revision ID: 20261027_0002
Revises: 20261027_0001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261027_0002"
down_revision: Union[str, None] = "20261027_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("missing_person_cases", sa.Column("date_of_birth", sa.Date(), nullable=True))
    op.add_column("missing_person_cases", sa.Column("last_seen_location", sa.String(length=255), nullable=True))
    op.add_column("missing_person_cases", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sightings", sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sightings", sa.Column("location", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("sightings", "location")
    op.drop_column("sightings", "observed_at")
    op.drop_column("missing_person_cases", "last_seen_at")
    op.drop_column("missing_person_cases", "last_seen_location")
    op.drop_column("missing_person_cases", "date_of_birth")
