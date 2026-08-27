"""Import every model so `Base.metadata` is fully populated before Alembic
(or `Base.metadata.create_all`) inspects it. Nothing here is used directly —
the imports are the point.
"""
from app.db.models.agent import (  # noqa: F401
    Agent,
    AgentVersion,
    RegressionCase,
    RegressionRun,
    ScenarioType,
    UserPersona,
)
from app.db.models.audit import AuditLog  # noqa: F401
from app.db.models.case import (  # noqa: F401
    BoundaryDecision,
    Case,
    Cutpoint,
    Document,
    DynamicConversation,
    DynamicConversationTurn,
    MockEntry,
    PersonaField,
    PipelineRun,
    Query,
    QueryVariant,
    ReviewFlag,
    StageMap,
)
from app.db.models.setting import AppSetting  # noqa: F401
from app.db.models.standard import (  # noqa: F401
    EvalCriterion,
    LegalBasisRef,
    RedLine,
    StandardCard,
    StandardCardCriterion,
)
from app.db.models.user import User  # noqa: F401

__all__ = [
    "Agent",
    "AgentVersion",
    "RegressionCase",
    "RegressionRun",
    "ScenarioType",
    "UserPersona",
    "AppSetting",
    "AuditLog",
    "DynamicConversation",
    "DynamicConversationTurn",
    "BoundaryDecision",
    "Case",
    "Cutpoint",
    "Document",
    "MockEntry",
    "PersonaField",
    "PipelineRun",
    "Query",
    "QueryVariant",
    "ReviewFlag",
    "StageMap",
    "EvalCriterion",
    "LegalBasisRef",
    "RedLine",
    "StandardCard",
    "StandardCardCriterion",
    "User",
]
