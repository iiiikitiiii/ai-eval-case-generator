"""Server-managed dynamic query conversations and append-only turns.

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    # query_id/variant_id are logical source identifiers rather than foreign
    # keys because Agent F replaces those source rows when it is rerun.
    op.create_table(
        "dynamic_conversations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("query_id", UUID, nullable=False),
        sa.Column("variant_id", UUID, nullable=False),
        sa.Column("started_by", UUID, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="awaiting_response"),
        sa.Column("current_round", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("context_snapshot", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("stop_reason", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_dynamic_conversations_query_id", "dynamic_conversations", ["query_id"])
    op.create_index(
        "uq_dynamic_conversations_active_actor_query",
        "dynamic_conversations",
        ["started_by", "query_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('awaiting_response', 'generating', 'generation_failed')"
        ),
    )

    op.create_table(
        "dynamic_conversation_turns",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "conversation_id",
            UUID,
            sa.ForeignKey("dynamic_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("user_messages", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("image_seqs", postgresql.ARRAY(sa.Integer()), nullable=False, server_default="{}"),
        sa.Column("tested_response", sa.Text(), nullable=True),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("token_usage", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "conversation_id",
            "round",
            name="uq_dynamic_conversation_turns_conversation_round",
        ),
    )
    op.create_index(
        "ix_dynamic_conversation_turns_conversation_id",
        "dynamic_conversation_turns",
        ["conversation_id"],
    )


def downgrade() -> None:
    op.drop_table("dynamic_conversation_turns")
    op.drop_index(
        "uq_dynamic_conversations_active_actor_query",
        table_name="dynamic_conversations",
    )
    op.drop_index("ix_dynamic_conversations_query_id", table_name="dynamic_conversations")
    op.drop_table("dynamic_conversations")
