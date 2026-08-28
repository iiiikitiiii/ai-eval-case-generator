"""Persist tested-system response images and transcriptions on dynamic turns.

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A JSON array preserves attachment order while keeping image bytes out of
    # PostgreSQL. Existing text-only turns receive an empty attachment list.
    op.add_column(
        "dynamic_conversation_turns",
        sa.Column(
            "tested_response_images",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    # Keep the screenshot transcription beside its image references. It stays
    # null for text-only turns and until multimodal generation succeeds.
    op.add_column(
        "dynamic_conversation_turns",
        sa.Column("tested_response_raw_content", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dynamic_conversation_turns", "tested_response_raw_content")
    op.drop_column("dynamic_conversation_turns", "tested_response_images")
