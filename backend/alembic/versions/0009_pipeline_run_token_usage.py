"""pipeline_runs.token_usage — real per-call token counts (provider/model/
prompt/completion/total), captured from stream_options.include_usage.
Feeds the board's quality-signals token aggregation.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pipeline_runs", sa.Column("token_usage", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("pipeline_runs", "token_usage")
