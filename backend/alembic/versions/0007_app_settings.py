"""app_settings — generic key/value runtime config, first row is
llm_provider (minimax/kimi switch, selectable from Prompt 后台 without a
restart — see app/db/models/setting.py).

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(60), primary_key=True),
        sa.Column("value", sa.String(200), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
