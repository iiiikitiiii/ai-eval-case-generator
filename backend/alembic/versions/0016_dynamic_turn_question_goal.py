"""Persist the internal goal and expected answer points for each dynamic turn.

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing conversations remain compatible with a null goal and empty
    # points, while every newly generated turn is validated before persistence.
    op.add_column(
        "dynamic_conversation_turns",
        sa.Column("question_goal", sa.Text(), nullable=True),
    )
    op.add_column(
        "dynamic_conversation_turns",
        sa.Column(
            "expected_answer_points",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )


def downgrade() -> None:
    op.drop_column("dynamic_conversation_turns", "expected_answer_points")
    op.drop_column("dynamic_conversation_turns", "question_goal")
