"""pipeline_runs.progress_note — rolling snapshot of the model's streamed
reasoning_content while a run is in flight (overwritten every couple
seconds, not appended), so the already-polling trace page has something
real to show instead of a static "运行中".

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pipeline_runs", sa.Column("progress_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("pipeline_runs", "progress_note")
