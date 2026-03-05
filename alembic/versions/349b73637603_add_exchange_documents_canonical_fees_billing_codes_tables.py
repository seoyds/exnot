"""add exchange_documents canonical_fees billing_codes tables

Revision ID: 349b73637603
Revises: 0a23a23c0e6e
Create Date: 2026-03-05 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "349b73637603"
down_revision: str | None = "0a23a23c0e6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- Enum types ---
    documentcategory = sa.Enum(
        "FEE_SCHEDULE",
        "PROTOCOL_SPEC",
        "REGULATORY_FILING",
        "MEMBERSHIP_AGREEMENT",
        "CIRCULAR_NOTICE",
        "OTHER",
        name="documentcategory",
    )
    documentcategory.create(op.get_bind(), checkfirst=True)

    documentstatus = sa.Enum(
        "DISCOVERED",
        "CLASSIFIED",
        "APPROVED",
        "REJECTED",
        "STALE",
        name="documentstatus",
    )
    documentstatus.create(op.get_bind(), checkfirst=True)

    billingprotocol = sa.Enum(
        "FIX",
        "BINARY",
        "SRO",
        "OTHER",
        name="billingprotocol",
    )
    billingprotocol.create(op.get_bind(), checkfirst=True)

    # --- canonical_fees table (must be created before tables that reference it) ---
    op.create_table(
        "canonical_fees",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("canonical_code", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column(
            "fee_type",
            sa.Enum(
                "MAKER",
                "TAKER",
                "ROUTING",
                "ORF",
                "TRANSACTION",
                "CLEARING",
                "CONNECTIVITY",
                "MARKET_DATA",
                "MEMBERSHIP",
                "CROSSING_FEE",
                "PIM_FEE",
                "RESPONSE_FEE",
                "BREAK_UP_REBATE",
                "SURCHARGE",
                "CANCELLATION",
                "STOCK_HANDLING",
                name="feetype",
                create_constraint=False,
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=50), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_code"),
    )
    op.create_index(
        op.f("ix_canonical_fees_canonical_code"),
        "canonical_fees",
        ["canonical_code"],
        unique=True,
    )

    # --- exchange_documents table ---
    op.create_table(
        "exchange_documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("exchange_id", sa.UUID(), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=False),
        sa.Column("url_pattern", sa.String(length=500), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column(
            "doc_category",
            documentcategory,
            nullable=False,
            server_default="OTHER",
        ),
        sa.Column(
            "status",
            documentstatus,
            nullable=False,
            server_default="DISCOVERED",
        ),
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("classification_confidence", sa.Float(), nullable=True),
        sa.Column("classification_reasoning", sa.Text(), nullable=True),
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_fetched_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "discovered_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["exchange_id"], ["exchanges.id"]),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_exchange_documents_exchange_id"),
        "exchange_documents",
        ["exchange_id"],
        unique=False,
    )

    # --- billing_codes table ---
    op.create_table(
        "billing_codes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("exchange_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column(
            "protocol",
            billingprotocol,
            nullable=False,
            server_default="OTHER",
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("canonical_fee_id", sa.Integer(), nullable=True),
        sa.Column("source_document_id", sa.UUID(), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("tag_number", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["exchange_id"], ["exchanges.id"]),
        sa.ForeignKeyConstraint(["canonical_fee_id"], ["canonical_fees.id"]),
        sa.ForeignKeyConstraint(["source_document_id"], ["exchange_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_billing_codes_exchange_id"),
        "billing_codes",
        ["exchange_id"],
        unique=False,
    )

    # --- New columns on normalized_fees ---
    op.add_column(
        "normalized_fees",
        sa.Column("canonical_fee_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "normalized_fees",
        sa.Column("exchange_fee_code", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "normalized_fees",
        sa.Column("exchange_fee_name", sa.String(length=200), nullable=True),
    )
    op.create_foreign_key(
        "fk_normalized_fees_canonical_fee_id",
        "normalized_fees",
        "canonical_fees",
        ["canonical_fee_id"],
        ["id"],
    )


def downgrade() -> None:
    # --- Drop new columns on normalized_fees ---
    op.drop_constraint(
        "fk_normalized_fees_canonical_fee_id",
        "normalized_fees",
        type_="foreignkey",
    )
    op.drop_column("normalized_fees", "exchange_fee_name")
    op.drop_column("normalized_fees", "exchange_fee_code")
    op.drop_column("normalized_fees", "canonical_fee_id")

    # --- Drop billing_codes ---
    op.drop_index(op.f("ix_billing_codes_exchange_id"), table_name="billing_codes")
    op.drop_table("billing_codes")

    # --- Drop exchange_documents ---
    op.drop_index(
        op.f("ix_exchange_documents_exchange_id"),
        table_name="exchange_documents",
    )
    op.drop_table("exchange_documents")

    # --- Drop canonical_fees ---
    op.drop_index(op.f("ix_canonical_fees_canonical_code"), table_name="canonical_fees")
    op.drop_table("canonical_fees")

    # --- Drop enum types ---
    sa.Enum(name="billingprotocol").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="documentstatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="documentcategory").drop(op.get_bind(), checkfirst=True)
