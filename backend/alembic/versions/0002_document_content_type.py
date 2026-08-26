"""add documents.content_type — needed to send the right media_type to the vision model

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("content_type", sa.String(60), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "content_type")
