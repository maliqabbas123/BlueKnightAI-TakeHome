"""collaborative reports

Revision ID: 20260529_0001
Revises:
Create Date: 2026-05-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "20260529_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'edit_source') THEN
                CREATE TYPE edit_source AS ENUM ('human', 'ai_rewrite', 'revert');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'share_permission') THEN
                CREATE TYPE share_permission AS ENUM ('view', 'edit');
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id BIGSERIAL PRIMARY KEY,
            org_id BIGINT NOT NULL,
            email TEXT UNIQUE NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS market_research_reports (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            company_name TEXT,
            company_url TEXT,
            sections JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_sections (
            id BIGSERIAL PRIMARY KEY,
            report_id BIGINT NOT NULL REFERENCES market_research_reports(id) ON DELETE CASCADE,
            section_key TEXT NOT NULL,
            content JSONB NOT NULL,
            version INT NOT NULL DEFAULT 1,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by_user_id BIGINT NOT NULL REFERENCES users(id),
            UNIQUE (report_id, section_key)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_section_edits (
            id BIGSERIAL PRIMARY KEY,
            report_id BIGINT NOT NULL REFERENCES market_research_reports(id) ON DELETE CASCADE,
            section_key TEXT NOT NULL,
            version_before INT NOT NULL,
            version_after INT NOT NULL,
            content_before JSONB NOT NULL,
            content_after JSONB NOT NULL,
            editor_user_id BIGINT NOT NULL REFERENCES users(id),
            source edit_source NOT NULL,
            ts TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS report_shares (
            id BIGSERIAL PRIMARY KEY,
            report_id BIGINT NOT NULL REFERENCES market_research_reports(id) ON DELETE CASCADE,
            target_user_id BIGINT NOT NULL REFERENCES users(id),
            permission share_permission NOT NULL,
            granted_by_user_id BIGINT NOT NULL REFERENCES users(id),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            revoked_at TIMESTAMPTZ NULL
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS report_section_edits_history_idx
        ON report_section_edits (report_id, section_key, ts DESC)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS report_shares_active_uniq
        ON report_shares (report_id, target_user_id)
        WHERE revoked_at IS NULL
        """
    )
    op.execute(
        """
        INSERT INTO report_sections (
            report_id, section_key, content, version, updated_by_user_id, updated_at
        )
        SELECT
            r.id,
            section_data.key,
            section_data.value,
            1,
            r.user_id,
            r.created_at
        FROM market_research_reports AS r
        CROSS JOIN LATERAL jsonb_each(r.sections) AS section_data(key, value)
        ON CONFLICT (report_id, section_key) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS report_shares_active_uniq")
    op.execute("DROP INDEX IF EXISTS report_section_edits_history_idx")
    op.execute("DROP TABLE IF EXISTS report_shares")
    op.execute("DROP TABLE IF EXISTS report_section_edits")
    op.execute("DROP TABLE IF EXISTS report_sections")
    op.execute("DROP TYPE IF EXISTS share_permission")
    op.execute("DROP TYPE IF EXISTS edit_source")
