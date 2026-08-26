"""regression_runs.triggered_by — who clicked "run regression suite".
Needed for the version list's "最近回归时间/结果/执行人/发布状态" columns
(《交互体验优化需求》P0-1) — regression_runs previously had no actor at all.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-20

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "regression_runs",
        sa.Column("triggered_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("regression_runs", "triggered_by")
