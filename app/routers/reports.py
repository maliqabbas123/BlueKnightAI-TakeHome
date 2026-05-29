from fastapi import APIRouter, Depends, Header, Query, Response, status

from app.auth import CurrentUser, get_current_user
from app.database import get_session
from app.llm_client import LLMClient, llm_client
from app.schemas import AIRewriteRequest, SectionPatch, ShareCreate
from app.services import reports as service


router = APIRouter(prefix="/reports", tags=["reports"])


def get_llm_client() -> LLMClient:
    return llm_client


@router.post("/{report_id}/shares", status_code=status.HTTP_201_CREATED)
async def create_share(
    report_id: int,
    body: ShareCreate,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    access = await service.load_access(session, report_id, current_user)
    share = await service.create_share(
        session,
        access=access,
        target_user_id=body.target_user_id,
        permission=body.permission,
    )
    return {"share": share}


@router.delete("/{report_id}/shares/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share(
    report_id: int,
    share_id: int,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    access = await service.load_access(session, report_id, current_user)
    await service.revoke_share(session, access=access, share_id=share_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{report_id}/shares")
async def list_shares(
    report_id: int,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    access = await service.load_access(session, report_id, current_user)
    return {"shares": await service.list_shares(session, access=access)}


@router.get("/{report_id}")
async def get_report(
    report_id: int,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    access = await service.load_access(session, report_id, current_user)
    return await service.get_report(session, access=access)


@router.get("/{report_id}/sections/{section_key}")
async def get_section(
    report_id: int,
    section_key: str,
    response: Response,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    access = await service.load_access(session, report_id, current_user)
    section = await service.get_section(session, access=access, section_key=section_key)
    response.headers["ETag"] = f'"{section["version"]}"'
    return section


@router.patch("/{report_id}/sections/{section_key}")
async def patch_section(
    report_id: int,
    section_key: str,
    body: SectionPatch,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    access = await service.load_access(session, report_id, current_user)
    expected_version = service.parse_if_match(if_match)
    result = await service.write_section(
        session,
        access=access,
        section_key=section_key,
        expected_version=expected_version,
        content=body.content,
        source="human",
    )
    response.headers["ETag"] = f'"{result["version"]}"'
    return result


@router.get("/{report_id}/sections/{section_key}/history")
async def list_history(
    report_id: int,
    section_key: str,
    limit: int = Query(default=25, ge=1, le=100),
    cursor: int | None = Query(default=None, ge=1),
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    access = await service.load_access(session, report_id, current_user)
    return await service.list_history(
        session,
        access=access,
        section_key=section_key,
        limit=limit,
        cursor=cursor,
    )


@router.post("/{report_id}/sections/{section_key}/revert/{edit_id}")
async def revert_section(
    report_id: int,
    section_key: str,
    edit_id: int,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
):
    access = await service.load_access(session, report_id, current_user)
    return await service.revert_section(session, access=access, section_key=section_key, edit_id=edit_id)


@router.post("/{report_id}/sections/{section_key}/ai-rewrite")
async def ai_rewrite(
    report_id: int,
    section_key: str,
    body: AIRewriteRequest,
    session=Depends(get_session),
    current_user: CurrentUser = Depends(get_current_user),
    client: LLMClient = Depends(get_llm_client),
):
    access = await service.load_access(session, report_id, current_user)
    return await service.ai_rewrite_section(
        session,
        access=access,
        section_key=section_key,
        instruction=body.instruction,
        llm_client=client,
    )
