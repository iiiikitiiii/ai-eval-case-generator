"""cutpoints.type_code becomes nullable — the C1-C6 classification was an
earlier session's invention, never present in any business document (see
app/import_scenario_standards.py's SIX_STAGE_CODES docstring for the real
six-stage journey model this replaces it with). Historical rows keep their
old value; new cutpoints going forward leave it null.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("cutpoints", "type_code", existing_type=sa.String(80), nullable=True)


def downgrade() -> None:
    op.alter_column("cutpoints", "type_code", existing_type=sa.String(80), nullable=False)
