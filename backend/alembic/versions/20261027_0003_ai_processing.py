"""Persist AI processing inputs, representations, and candidate metadata.

Revision ID: 20261027_0003
Revises: 20261027_0002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20261027_0003"
down_revision: Union[str, None] = "20261027_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reference_images", sa.Column("representation", postgresql.JSONB(), nullable=True))
    op.add_column("reference_images", sa.Column("processing_signature", sa.String(length=255), nullable=True))
    op.add_column("search_jobs", sa.Column("query_storage_key", sa.String(length=512), nullable=True))
    op.add_column("search_jobs", sa.Column("error_message", sa.Text(), nullable=True))
    op.add_column("search_jobs", sa.Column("progress", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("candidate_matches", sa.Column("reference_image_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("candidate_matches", sa.Column("distance", sa.Float(), nullable=True))
    op.add_column("candidate_matches", sa.Column("frame_timestamp_seconds", sa.Float(), nullable=True))
    op.add_column("candidate_matches", sa.Column("source_storage_key", sa.String(length=512), nullable=True))
    op.create_foreign_key(
        "fk_candidate_matches_reference_image_id", "candidate_matches", "reference_images",
        ["reference_image_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_candidate_matches_reference_image_id", "candidate_matches", type_="foreignkey")
    for table, column in (
        ("candidate_matches", "source_storage_key"),
        ("candidate_matches", "frame_timestamp_seconds"),
        ("candidate_matches", "distance"),
        ("candidate_matches", "reference_image_id"),
        ("search_jobs", "progress"),
        ("search_jobs", "error_message"),
        ("search_jobs", "query_storage_key"),
        ("reference_images", "processing_signature"),
        ("reference_images", "representation"),
    ):
        op.drop_column(table, column)
