"""regression_cases gains agent_code — which agent's output a golden case's assertions target

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("regression_cases", sa.Column("agent_code", sa.String(4), nullable=False, server_default="A"))
    op.alter_column("regression_cases", "agent_code", server_default=None)


def downgrade() -> None:
    op.drop_column("regression_cases", "agent_code")
