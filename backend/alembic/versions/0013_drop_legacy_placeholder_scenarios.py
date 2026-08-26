"""Deletes the 7 phase-1 placeholder ScenarioType rows (result_interpretation/
metastasis_risk/shared_decision/med_safety/symptom_report/psych_crisis/
info_verify) that app.seed_agents.SCENARIO_TYPES used to seed — superseded
by the real 49-scenario import (app/import_scenario_standards.py) long ago,
already flagged inactive by a past cleanup, but never actually deleted.
Found while tracking down a stale "J01–J08" string (agent_b.py/sandbox.py):
these rows still carry the fabricated 8-stage codes and were showing up as
dead options in the board's scenario-type filter dropdown and (as of this
same session) the new Agent F scenario picker's underlying query, even
though `active=False` already kept them out of actual generation. Verified
before writing this migration: 0 Query rows reference any of these 7 codes,
0 StandardCard rows reference their ids — safe to delete outright, not just
deactivate. Also fixes agents.oneline for B, which still said "J01–J08"
in the live row (the source in seed_agents.py was already corrected at
some point, but seeding is insert-if-missing and never re-applied it).

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-20

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LEGACY_CODES = (
    "result_interpretation", "metastasis_risk", "shared_decision",
    "med_safety", "symptom_report", "psych_crisis", "info_verify",
)


def upgrade() -> None:
    codes_sql = ", ".join(f"'{c}'" for c in _LEGACY_CODES)
    op.execute(f"DELETE FROM scenario_types WHERE code IN ({codes_sql}) AND scenario_number IS NULL")
    op.execute(
        "UPDATE agents SET oneline = '结构化时间线 → J01–J06 阶段归类（业务方六阶段旅程），边界判断必须显式标注。' "
        "WHERE code = 'B'"
    )


def downgrade() -> None:
    # 占位数据不值得在 downgrade 里重新造回去——这本来就是一次清理，不是
    # 需要可逆的 schema 变更。oneline 的旧值也没有保留的必要。
    pass
