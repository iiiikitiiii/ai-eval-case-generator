"""user_personas + query_variants (multi-turn, persona-scripted test cases)
+ queries gains test_direction/test_background/test_image_seqs/test_image_note

Backs 《专病管家跑测方案811.xlsx》's real test-case design: one test case
(裂点 × 场景) is realized as up to 4 candidate persona scripts
(患者本人/家属 × 低/较高认知), each a multi-turn conversation with an
overarching behavior arc, plus an explicit, curated list of which case
images actually get sent to the product under test.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "user_personas",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("cognition", sa.String(10), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("behavior_guideline", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("code", name="uq_user_personas_code"),
    )

    op.add_column("queries", sa.Column("test_direction", sa.Text(), nullable=True))
    op.add_column("queries", sa.Column("test_background", sa.Text(), nullable=True))
    op.add_column("queries", sa.Column("test_image_seqs", postgresql.ARRAY(sa.Integer()), nullable=False, server_default="{}"))
    op.add_column("queries", sa.Column("test_image_note", sa.Text(), nullable=True))

    op.create_table(
        "query_variants",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("query_id", UUID, sa.ForeignKey("queries.id", ondelete="CASCADE"), nullable=False),
        sa.Column("persona_id", UUID, sa.ForeignKey("user_personas.id"), nullable=False),
        sa.Column("persona_note", sa.Text(), nullable=False),
        sa.Column("turns", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("behavior_logic", sa.Text(), nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_query_variants_query_id", "query_variants", ["query_id"])


def downgrade() -> None:
    op.drop_table("query_variants")
    op.drop_column("queries", "test_image_note")
    op.drop_column("queries", "test_image_seqs")
    op.drop_column("queries", "test_background")
    op.drop_column("queries", "test_direction")
    op.drop_table("user_personas")
