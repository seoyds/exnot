"""merge heads

Revision ID: bf4e478bfc71
Revises: 349b73637603, 733e1e3608e4
Create Date: 2026-03-06 00:28:44.043907
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bf4e478bfc71'
down_revision: Union[str, None] = ('349b73637603', '733e1e3608e4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
