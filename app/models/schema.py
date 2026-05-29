from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB


metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("org_id", BigInteger, nullable=False),
    Column("email", Text, nullable=False, unique=True),
)

market_research_reports = Table(
    "market_research_reports",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("user_id", BigInteger, nullable=False),
    Column("company_name", Text),
    Column("company_url", Text),
    Column("sections", JSONB, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

edit_source_enum = Enum("human", "ai_rewrite", "revert", name="edit_source")
share_permission_enum = Enum("view", "edit", name="share_permission")

report_sections = Table(
    "report_sections",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column(
        "report_id",
        BigInteger,
        ForeignKey("market_research_reports.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("section_key", Text, nullable=False),
    Column("content", JSONB, nullable=False),
    Column("version", Integer, nullable=False, server_default="1"),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_by_user_id", BigInteger, ForeignKey("users.id"), nullable=False),
    UniqueConstraint("report_id", "section_key", name="report_sections_report_id_section_key_key"),
)

report_section_edits = Table(
    "report_section_edits",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column(
        "report_id",
        BigInteger,
        ForeignKey("market_research_reports.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("section_key", Text, nullable=False),
    Column("version_before", Integer, nullable=False),
    Column("version_after", Integer, nullable=False),
    Column("content_before", JSONB, nullable=False),
    Column("content_after", JSONB, nullable=False),
    Column("editor_user_id", BigInteger, ForeignKey("users.id"), nullable=False),
    Column("source", edit_source_enum, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

report_shares = Table(
    "report_shares",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column(
        "report_id",
        BigInteger,
        ForeignKey("market_research_reports.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("target_user_id", BigInteger, ForeignKey("users.id"), nullable=False),
    Column("permission", share_permission_enum, nullable=False),
    Column("granted_by_user_id", BigInteger, ForeignKey("users.id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("revoked_at", DateTime(timezone=True)),
)

Index(
    "report_section_edits_history_idx",
    report_section_edits.c.report_id,
    report_section_edits.c.section_key,
    report_section_edits.c.ts.desc(),
)
Index(
    "report_shares_active_uniq",
    report_shares.c.report_id,
    report_shares.c.target_user_id,
    unique=True,
    postgresql_where=report_shares.c.revoked_at.is_(None),
)

