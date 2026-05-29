import logging
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.llm_client import LLMClient, LLMMessage
from app.repository import reports as repo
from app.request_context import current_request_id
from app.services.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    PreconditionFailedError,
    UpstreamError,
)


logger = logging.getLogger("app.writes")


def _iso_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.isoformat().replace("+00:00", "Z") if hasattr(value, "isoformat") else value
        for key, value in row.items()
    }


class Access:
    def __init__(self, row: dict[str, Any], current_user: CurrentUser) -> None:
        self.report_id = int(row["report_id"])
        self.owner_user_id = int(row["owner_user_id"])
        self.company_name = row["company_name"]
        self.company_url = row["company_url"]
        self.permission = row["permission"]
        self.current_user = current_user
        self.is_owner = self.owner_user_id == current_user.user_id
        self.is_editor = self.permission == "edit"
        self.is_viewer = self.permission == "view"

    @property
    def has_any(self) -> bool:
        return self.is_owner or self.is_editor or self.is_viewer

    @property
    def can_edit(self) -> bool:
        return self.is_owner or self.is_editor

    def require_owner(self) -> None:
        if not self.is_owner:
            raise ForbiddenError()

    def require_any(self) -> None:
        if not self.has_any:
            raise ForbiddenError()

    def require_edit(self) -> None:
        if not self.can_edit:
            raise ForbiddenError()


async def load_access(session: AsyncSession, report_id: int, current_user: CurrentUser) -> Access:
    row = await repo.get_report_access(session, report_id, current_user.user_id)
    if row is None:
        raise NotFoundError()
    access = Access(row, current_user)
    return access


def parse_if_match(value: str | None) -> int:
    if value is None:
        raise BadRequestError("missing If-Match")
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        value = value[1:-1]
    try:
        version = int(value)
    except ValueError:
        raise BadRequestError("invalid If-Match")
    if version < 1:
        raise BadRequestError("invalid If-Match")
    return version


async def create_share(
    session: AsyncSession,
    *,
    access: Access,
    target_user_id: int,
    permission: str,
) -> dict[str, Any]:
    access.require_owner()
    target_org = await repo.get_user_org(session, target_user_id)
    if target_org is None:
        raise NotFoundError("target user not found")
    if target_org != access.current_user.org_id:
        raise ForbiddenError("cross-org share forbidden")
    try:
        share = await repo.create_share(
            session,
            report_id=access.report_id,
            target_user_id=target_user_id,
            permission=permission,
            granted_by_user_id=access.current_user.user_id,
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise ConflictError("active share already exists")
    _log_write(access, "share_create", version=None)
    return _iso_row(share)


async def revoke_share(session: AsyncSession, *, access: Access, share_id: int) -> None:
    access.require_owner()
    await repo.revoke_share(session, share_id=share_id, report_id=access.report_id)
    await session.commit()
    _log_write(access, "share_revoke", version=None)


async def list_shares(session: AsyncSession, *, access: Access) -> list[dict[str, Any]]:
    access.require_owner()
    return [_iso_row(row) for row in await repo.list_shares(session, access.report_id)]


async def get_report(session: AsyncSession, *, access: Access) -> dict[str, Any]:
    access.require_any()
    sections = [_iso_row(row) for row in await repo.list_sections(session, access.report_id)]
    return {
        "report_id": access.report_id,
        "company_name": access.company_name,
        "company_url": access.company_url,
        "sections": sections,
    }


async def get_section(session: AsyncSession, *, access: Access, section_key: str) -> dict[str, Any]:
    access.require_any()
    section = await repo.get_section(session, access.report_id, section_key)
    if section is None:
        raise NotFoundError()
    return _iso_row(section)


async def write_section(
    session: AsyncSession,
    *,
    access: Access,
    section_key: str,
    expected_version: int,
    content: Any,
    source: str,
) -> dict[str, Any]:
    access.require_edit()
    result = await repo.update_section_with_audit(
        session,
        report_id=access.report_id,
        section_key=section_key,
        expected_version=expected_version,
        content_after=content,
        editor_user_id=access.current_user.user_id,
        source=source,
    )
    await session.commit()
    if result is None:
        existing = await repo.get_section(session, access.report_id, section_key)
        if existing is None:
            raise NotFoundError()
        raise PreconditionFailedError("section version mismatch")
    _log_write(access, source, section_key=section_key, version=result["version"])
    return _iso_row(result)


async def list_history(
    session: AsyncSession,
    *,
    access: Access,
    section_key: str,
    limit: int,
    cursor: int | None,
) -> dict[str, Any]:
    access.require_any()
    limit = max(1, min(limit, 100))
    rows = await repo.list_history(
        session,
        report_id=access.report_id,
        section_key=section_key,
        limit=limit + 1,
        cursor=cursor,
    )
    next_cursor = None
    if len(rows) > limit:
        next_cursor = rows[limit - 1]["id"]
        rows = rows[:limit]
    return {"edits": [_iso_row(row) for row in rows], "next_cursor": next_cursor}


async def revert_section(
    session: AsyncSession,
    *,
    access: Access,
    section_key: str,
    edit_id: int,
) -> dict[str, Any]:
    access.require_edit()
    edit = await repo.get_edit(session, report_id=access.report_id, section_key=section_key, edit_id=edit_id)
    if edit is None:
        raise NotFoundError()
    current = await repo.get_section(session, access.report_id, section_key)
    if current is None:
        raise NotFoundError()
    try:
        return await write_section(
            session,
            access=access,
            section_key=section_key,
            expected_version=current["version"],
            content=edit["content_before"],
            source="revert",
        )
    except PreconditionFailedError as exc:
        raise ConflictError("section changed during revert") from exc


async def ai_rewrite_section(
    session: AsyncSession,
    *,
    access: Access,
    section_key: str,
    instruction: str,
    llm_client: LLMClient,
) -> dict[str, Any]:
    access.require_edit()
    current = await repo.get_section(session, access.report_id, section_key)
    if current is None:
        raise NotFoundError()
    messages = [
        LLMMessage(role="system", content="Rewrite the market research report section as instructed."),
        LLMMessage(role="user", content=f"Instruction: {instruction}\n\nSection JSON: {current['content']}"),
    ]
    try:
        response = await llm_client.call(
            operation="report.section.ai_rewrite",
            request_id=current_request_id(),
            messages=messages,
            model=None,
        )
    except Exception as exc:
        raise UpstreamError("LLM rewrite failed") from exc
    return await write_section(
        session,
        access=access,
        section_key=section_key,
        expected_version=current["version"],
        content={"rewritten": response.content},
        source="ai_rewrite",
    )


def _log_write(access: Access, action: str, *, section_key: str | None = None, version: int | None) -> None:
    parts = [
        f"request_id={current_request_id()}",
        f"user_id={access.current_user.user_id}",
        f"report_id={access.report_id}",
        f"action={action}",
    ]
    if section_key is not None:
        parts.append(f"section_key={section_key}")
    if version is not None:
        parts.append(f"version={version}")
    logger.info(" ".join(parts))
