"""real scenario library fields + eval_criteria / red_lines / legal_basis_refs / standard_cards

Backs the import of doc/专病管家测评标准-场景清单+标准.xlsx
(see app/import_scenario_standards.py):
- scenario_types gains scenario_number/source/consultation_volume so the 49
  real scenarios can replace the phase-1 placeholder rows idempotently.
- eval_criteria / legal_basis_refs / red_lines: fixed global reference
  tables, not per-case, not per-scenario.
- standard_cards / standard_card_criteria: one full scoring rubric per
  scenario (only 1 of 49 scenarios has one so far — that's expected, not
  a partial import).
- queries.has_standard_card: snapshot at generation time of whether the
  scenario F used had a standard card backing it.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column("scenario_types", sa.Column("scenario_number", sa.Integer(), nullable=True))
    op.add_column("scenario_types", sa.Column("source", sa.String(20), nullable=True))
    op.add_column("scenario_types", sa.Column("consultation_volume", sa.Integer(), nullable=True))
    op.alter_column("scenario_types", "name", type_=sa.String(120))
    op.create_unique_constraint("uq_scenario_types_scenario_number", "scenario_types", ["scenario_number"])

    op.add_column("queries", sa.Column("has_standard_card", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        "eval_criteria",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("code", sa.String(8), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("category_weight", sa.Numeric(3, 2), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("evaluation_boundary", sa.Text(), nullable=True),
        sa.Column("max_points", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(20), nullable=True),
        sa.UniqueConstraint("code", name="uq_eval_criteria_code"),
    )

    op.create_table(
        "legal_basis_refs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("code", sa.String(4), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("articles", sa.String(120), nullable=True),
        sa.Column("key_points", sa.Text(), nullable=True),
        sa.Column("usage_note", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(300), nullable=True),
        sa.Column("nature", sa.String(20), nullable=True),
        sa.UniqueConstraint("code", name="uq_legal_basis_refs_code"),
    )

    op.create_table(
        "red_lines",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("judgment_criteria", sa.Text(), nullable=False),
        sa.Column("evidence_requirements", sa.Text(), nullable=True),
        sa.Column("legal_basis_codes", postgresql.ARRAY(sa.String(4)), nullable=False, server_default="{}"),
        sa.Column("verdict_rule", sa.String(60), nullable=True),
        sa.UniqueConstraint("seq", name="uq_red_lines_seq"),
    )

    op.create_table(
        "standard_cards",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("scenario_type_id", UUID, sa.ForeignKey("scenario_types.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.String(20), nullable=True),
        sa.Column("patient_need", sa.Text(), nullable=True),
        sa.Column("evaluation_purpose", sa.Text(), nullable=True),
        sa.Column("observation_conditions", sa.Text(), nullable=True),
        sa.Column("whats_right", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("whats_wrong", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("applicable_red_line_seqs", postgresql.ARRAY(sa.Integer()), nullable=False, server_default="{}"),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("scenario_type_id", name="uq_standard_cards_scenario_type_id"),
    )

    op.create_table(
        "standard_card_criteria",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("standard_card_id", UUID, sa.ForeignKey("standard_cards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("criterion_code", sa.String(8), nullable=False),
        sa.Column("tiers", postgresql.JSONB(), nullable=False),
    )
    op.create_index("ix_standard_card_criteria_card_id", "standard_card_criteria", ["standard_card_id"])


def downgrade() -> None:
    op.drop_table("standard_card_criteria")
    op.drop_table("standard_cards")
    op.drop_table("red_lines")
    op.drop_table("legal_basis_refs")
    op.drop_table("eval_criteria")
    op.drop_column("queries", "has_standard_card")
    op.drop_constraint("uq_scenario_types_scenario_number", "scenario_types", type_="unique")
    op.drop_column("scenario_types", "consultation_volume")
    op.drop_column("scenario_types", "source")
    op.drop_column("scenario_types", "scenario_number")
