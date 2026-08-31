"""Allow multiple active dynamic conversations per account and query.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ACTIVE_STATUS_SQL = (
    "status IN ('awaiting_response', 'generating', 'generation_failed')"
)


def upgrade() -> None:
    # Conversation IDs now select an exact run, so actor/query no longer needs
    # to identify a single unfinished row.
    op.drop_index(
        "uq_dynamic_conversations_active_actor_query",
        table_name="dynamic_conversations",
    )


def downgrade() -> None:
    # The prior schema cannot represent multiple active rows. Keep the newest
    # run active and stop older duplicates before restoring its unique index.
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY started_by, query_id
                        ORDER BY created_at DESC, id DESC
                    ) AS active_rank
                FROM dynamic_conversations
                WHERE status IN (
                    'awaiting_response', 'generating', 'generation_failed'
                )
            )
            UPDATE dynamic_conversations AS conversation
            SET
                status = 'abandoned',
                stop_reason = 'migration_0018_downgrade',
                last_error = NULL,
                finished_at = COALESCE(conversation.finished_at, now()),
                updated_at = now()
            FROM ranked
            WHERE conversation.id = ranked.id
              AND ranked.active_rank > 1
            """
        )
    )
    op.create_index(
        "uq_dynamic_conversations_active_actor_query",
        "dynamic_conversations",
        ["started_by", "query_id"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_STATUS_SQL),
    )
