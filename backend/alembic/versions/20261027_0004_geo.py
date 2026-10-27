"""Add case and sighting coordinates.

Revision ID: 20261027_0004
Revises: 20261027_0003
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261027_0004"
down_revision: Union[str, None] = "20261027_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("missing_person_cases", sa.Column("external_id", sa.String(length=128), nullable=True))
    op.create_unique_constraint("uq_missing_person_cases_external_id", "missing_person_cases", ["external_id"])
    op.add_column("sightings", sa.Column("external_id", sa.String(length=128), nullable=True))
    op.create_unique_constraint("uq_sightings_external_id", "sightings", ["external_id"])
    op.add_column("missing_person_cases", sa.Column("last_seen_latitude", sa.Float(), nullable=True))
    op.add_column("missing_person_cases", sa.Column("last_seen_longitude", sa.Float(), nullable=True))
    op.add_column("sightings", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("sightings", sa.Column("longitude", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_constraint("uq_sightings_external_id", "sightings", type_="unique")
    op.drop_column("sightings", "external_id")
    op.drop_constraint("uq_missing_person_cases_external_id", "missing_person_cases", type_="unique")
    op.drop_column("missing_person_cases", "external_id")
    op.drop_column("sightings", "longitude")
    op.drop_column("sightings", "latitude")
    op.drop_column("missing_person_cases", "last_seen_longitude")
    op.drop_column("missing_person_cases", "last_seen_latitude")
