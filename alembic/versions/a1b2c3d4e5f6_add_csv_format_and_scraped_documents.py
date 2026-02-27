"""add csv format and scraped_documents table

Revision ID: a1b2c3d4e5f6
Revises: f40cf4538f9a
Create Date: 2026-02-27 01:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f40cf4538f9a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add CSV value to feescheduleformat enum
    op.execute("ALTER TYPE feescheduleformat ADD VALUE IF NOT EXISTS 'CSV'")

    # Create scraped_documents table
    op.create_table(
        "scraped_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("snapshot_id", UUID(as_uuid=True), sa.ForeignKey("fee_schedule_snapshots.id"), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("source_url", sa.String(500), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("storage_path", sa.String(500), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("fetched_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_scraped_documents_snapshot_id", "scraped_documents", ["snapshot_id"])


def downgrade() -> None:
    op.drop_index("ix_scraped_documents_snapshot_id", table_name="scraped_documents")
    op.drop_table("scraped_documents")
    # Note: PostgreSQL doesn't support removing enum values, so CSV stays in the type.
