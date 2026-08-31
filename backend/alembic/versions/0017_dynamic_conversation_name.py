"""Add optional user-defined names to dynamic test records.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Null preserves the existing generated fallback label for historical runs.
    op.add_column(
        "dynamic_conversations",
        sa.Column("name", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dynamic_conversations", "name")
