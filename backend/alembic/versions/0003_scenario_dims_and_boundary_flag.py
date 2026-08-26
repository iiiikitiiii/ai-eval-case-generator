"""scenario_types gains journey_stages + feature_scenario; boundary_decisions gains needs_human

Resolves two open notes from doc/需求细节澄清.md:
1. journey × 测试场景 × 产品功能场景 三维映射——scenario_types 加两列承载
   journey_stages 和 feature_scenario；原有的 name/axis 就是"测试场景"那一维。
2. boundary_decisions.needs_human 补上——B 的 out_schema 一直在要求这个字段，
   之前没建列，模型给出的值实际上被静默丢弃了。

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-16

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("scenario_types", sa.Column("journey_stages", postgresql.ARRAY(sa.String(4)), nullable=False, server_default="{}"))
    op.add_column("scenario_types", sa.Column("feature_scenario", sa.String(120), nullable=True))
    op.add_column("boundary_decisions", sa.Column("needs_human", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("boundary_decisions", "needs_human")
    op.drop_column("scenario_types", "feature_scenario")
    op.drop_column("scenario_types", "journey_stages")
