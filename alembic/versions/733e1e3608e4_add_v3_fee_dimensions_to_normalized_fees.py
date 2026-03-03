"""add V3 fee dimensions to normalized_fees

Revision ID: 733e1e3608e4
Revises: 0a23a23c0e6e
Create Date: 2026-03-03 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '733e1e3608e4'
down_revision: Union[str, None] = '0a23a23c0e6e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('normalized_fees', sa.Column('origin_code', sa.String(length=30), nullable=True))
    op.add_column('normalized_fees', sa.Column('contra_origin_code', sa.String(length=30), nullable=True))
    op.add_column('normalized_fees', sa.Column('product_type', sa.String(length=20), nullable=True))
    op.add_column('normalized_fees', sa.Column('listing_type', sa.String(length=20), nullable=True))
    op.add_column('normalized_fees', sa.Column('penny_class', sa.String(length=20), nullable=True))
    op.add_column('normalized_fees', sa.Column('multi_listed', sa.Boolean(), nullable=True))
    op.add_column('normalized_fees', sa.Column('exec_venue', sa.String(length=20), nullable=True))
    op.add_column('normalized_fees', sa.Column('liquidity_role', sa.String(length=20), nullable=True))
    op.add_column('normalized_fees', sa.Column('auction_type', sa.String(length=30), nullable=True))
    op.add_column('normalized_fees', sa.Column('auction_role', sa.String(length=20), nullable=True))
    op.add_column('normalized_fees', sa.Column('fee_name', sa.String(length=500), nullable=True))
    op.add_column('normalized_fees', sa.Column('tier_level', sa.Integer(), nullable=True))
    op.add_column('normalized_fees', sa.Column('tier_condition_text', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('normalized_fees', 'tier_condition_text')
    op.drop_column('normalized_fees', 'tier_level')
    op.drop_column('normalized_fees', 'fee_name')
    op.drop_column('normalized_fees', 'auction_role')
    op.drop_column('normalized_fees', 'auction_type')
    op.drop_column('normalized_fees', 'liquidity_role')
    op.drop_column('normalized_fees', 'exec_venue')
    op.drop_column('normalized_fees', 'multi_listed')
    op.drop_column('normalized_fees', 'penny_class')
    op.drop_column('normalized_fees', 'listing_type')
    op.drop_column('normalized_fees', 'product_type')
    op.drop_column('normalized_fees', 'contra_origin_code')
    op.drop_column('normalized_fees', 'origin_code')
