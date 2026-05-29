from typing import Any

from sqlalchemy import and_, bindparam, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schema import (
    market_research_reports,
    report_section_edits,
    report_sections,
    report_shares,
    users,
)


async def get_user_org(session: AsyncSession, user_id: int) -> int | None:
    return await session.scalar(select(users.c.org_id).where(users.c.id == user_id))


async def get_report_access(session: AsyncSession, report_id: int, user_id: int) -> dict[str, Any] | None:
    stmt = (
        select(
            market_research_reports.c.id.label("report_id"),
            market_research_reports.c.user_id.label("owner_user_id"),
            market_research_reports.c.company_name,
            market_research_reports.c.company_url,
            report_shares.c.permission,
        )
        .select_from(
            market_research_reports.outerjoin(
                report_shares,
                and_(
                    report_shares.c.report_id == market_research_reports.c.id,
                    report_shares.c.target_user_id == user_id,
                    report_shares.c.revoked_at.is_(None),
                ),
            )
        )
        .where(market_research_reports.c.id == report_id)
    )
    row = (await session.execute(stmt)).mappings().first()
    return dict(row) if row else None


async def list_sections(session: AsyncSession, report_id: int) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(
                report_sections.c.section_key,
                report_sections.c.content,
                report_sections.c.version,
                report_sections.c.updated_at,
                report_sections.c.updated_by_user_id,
            )
            .where(report_sections.c.report_id == report_id)
            .order_by(report_sections.c.section_key)
        )
    ).mappings()
    return [dict(row) for row in rows]


async def get_section(session: AsyncSession, report_id: int, section_key: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            select(
                report_sections.c.report_id,
                report_sections.c.section_key,
                report_sections.c.content,
                report_sections.c.version,
                report_sections.c.updated_at,
                report_sections.c.updated_by_user_id,
            ).where(
                report_sections.c.report_id == report_id,
                report_sections.c.section_key == section_key,
            )
        )
    ).mappings().first()
    return dict(row) if row else None


async def create_share(
    session: AsyncSession,
    *,
    report_id: int,
    target_user_id: int,
    permission: str,
    granted_by_user_id: int,
) -> dict[str, Any]:
    stmt = (
        insert(report_shares)
        .values(
            report_id=report_id,
            target_user_id=target_user_id,
            permission=permission,
            granted_by_user_id=granted_by_user_id,
        )
        .returning(report_shares)
    )
    row = (await session.execute(stmt)).mappings().one()
    return dict(row)


async def revoke_share(session: AsyncSession, *, share_id: int, report_id: int) -> None:
    await session.execute(
        update(report_shares)
        .where(
            report_shares.c.id == share_id,
            report_shares.c.report_id == report_id,
            report_shares.c.revoked_at.is_(None),
        )
        .values(revoked_at=func.now())
    )


async def list_shares(session: AsyncSession, report_id: int) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(
                report_shares.c.id,
                report_shares.c.report_id,
                report_shares.c.target_user_id,
                report_shares.c.permission,
                report_shares.c.granted_by_user_id,
                report_shares.c.created_at,
                report_shares.c.revoked_at,
            )
            .where(report_shares.c.report_id == report_id, report_shares.c.revoked_at.is_(None))
            .order_by(report_shares.c.id)
        )
    ).mappings()
    return [dict(row) for row in rows]


async def update_section_with_audit(
    session: AsyncSession,
    *,
    report_id: int,
    section_key: str,
    expected_version: int,
    content_after: Any,
    editor_user_id: int,
    source: str,
) -> dict[str, Any] | None:
    stmt = text(
        """
        WITH old_section AS (
            SELECT report_id, section_key, content, version
            FROM report_sections
            WHERE report_id = :report_id AND section_key = :section_key
        ),
        updated_section AS (
            UPDATE report_sections
            SET
                content = :content_after,
                version = version + 1,
                updated_at = now(),
                updated_by_user_id = :editor_user_id
            WHERE report_id = :report_id
              AND section_key = :section_key
              AND version = :expected_version
            RETURNING report_id, section_key, content, version
        ),
        inserted_edit AS (
            INSERT INTO report_section_edits (
                report_id,
                section_key,
                version_before,
                version_after,
                content_before,
                content_after,
                editor_user_id,
                source
            )
            SELECT
                updated_section.report_id,
                updated_section.section_key,
                old_section.version,
                updated_section.version,
                old_section.content,
                updated_section.content,
                :editor_user_id,
                CAST(:source AS edit_source)
            FROM updated_section
            JOIN old_section
              ON old_section.report_id = updated_section.report_id
             AND old_section.section_key = updated_section.section_key
            RETURNING report_id, section_key, version_after AS version, content_after AS content
        )
        SELECT report_id, section_key, version, content FROM inserted_edit
        """
    ).bindparams(bindparam("content_after", type_=JSONB))
    row = (
        await session.execute(
            stmt,
            {
                "report_id": report_id,
                "section_key": section_key,
                "expected_version": expected_version,
                "content_after": content_after,
                "editor_user_id": editor_user_id,
                "source": source,
            },
        )
    ).mappings().first()
    return dict(row) if row else None


async def list_history(
    session: AsyncSession,
    *,
    report_id: int,
    section_key: str,
    limit: int,
    cursor: int | None,
) -> list[dict[str, Any]]:
    filters = [
        report_section_edits.c.report_id == report_id,
        report_section_edits.c.section_key == section_key,
    ]
    if cursor is not None:
        filters.append(report_section_edits.c.id < cursor)
    rows = (
        await session.execute(
            select(
                report_section_edits.c.id,
                report_section_edits.c.report_id,
                report_section_edits.c.section_key,
                report_section_edits.c.version_before,
                report_section_edits.c.version_after,
                report_section_edits.c.content_before,
                report_section_edits.c.content_after,
                report_section_edits.c.editor_user_id,
                report_section_edits.c.source,
                report_section_edits.c.ts,
            )
            .where(*filters)
            .order_by(report_section_edits.c.id.desc())
            .limit(limit)
        )
    ).mappings()
    return [dict(row) for row in rows]


async def get_edit(session: AsyncSession, *, report_id: int, section_key: str, edit_id: int) -> dict[str, Any] | None:
    row = (
        await session.execute(
            select(report_section_edits).where(
                report_section_edits.c.id == edit_id,
                report_section_edits.c.report_id == report_id,
                report_section_edits.c.section_key == section_key,
            )
        )
    ).mappings().first()
    return dict(row) if row else None
