from sqlalchemy import func, select

from app.database import SessionLocal
from app.llm_client import llm_client
from app.models.schema import report_section_edits


async def test_auth_required(client):
    response = await client.get("/reports/1")
    assert response.status_code == 401


async def test_owner_can_create_list_and_revoke_share_idempotently(client, auth_headers):
    response = await client.post(
        "/reports/1/shares",
        json={"target_user_id": 2, "permission": "edit"},
        headers=auth_headers(),
    )
    assert response.status_code == 201
    share_id = response.json()["share"]["id"]

    duplicate = await client.post(
        "/reports/1/shares",
        json={"target_user_id": 2, "permission": "edit"},
        headers=auth_headers(),
    )
    assert duplicate.status_code == 409

    listed = await client.get("/reports/1/shares", headers=auth_headers())
    assert listed.status_code == 200
    assert listed.json()["shares"][0]["target_user_id"] == 2

    first = await client.delete(f"/reports/1/shares/{share_id}", headers=auth_headers())
    second = await client.delete(f"/reports/1/shares/{share_id}", headers=auth_headers())
    assert first.status_code == 204
    assert second.status_code == 204


async def test_cross_org_share_forbidden(client, auth_headers):
    response = await client.post(
        "/reports/1/shares",
        json={"target_user_id": 4, "permission": "view"},
        headers=auth_headers(),
    )
    assert response.status_code == 403


async def test_non_owner_cannot_manage_shares(client, auth_headers):
    response = await client.get("/reports/1/shares", headers=auth_headers(user_id=2, org_id=1))
    assert response.status_code == 403


async def test_report_access_for_viewer_editor_and_denied_user(client, auth_headers):
    await client.post("/reports/1/shares", json={"target_user_id": 3, "permission": "view"}, headers=auth_headers())

    viewer = await client.get("/reports/1", headers=auth_headers(user_id=3, org_id=1))
    denied = await client.get("/reports/1", headers=auth_headers(user_id=2, org_id=1))
    assert viewer.status_code == 200
    assert len(viewer.json()["sections"]) == 3
    assert denied.status_code == 403


async def test_section_etag_patch_and_stale_conflict(client, auth_headers):
    section = await client.get("/reports/1/sections/executive_summary", headers=auth_headers())
    assert section.status_code == 200
    assert section.headers["etag"] == '"1"'

    missing = await client.patch(
        "/reports/1/sections/executive_summary",
        json={"content": {"text": "Updated"}},
        headers=auth_headers(),
    )
    assert missing.status_code == 400

    first = await client.patch(
        "/reports/1/sections/executive_summary",
        json={"content": {"text": "Updated"}},
        headers={**auth_headers(), "If-Match": '"1"'},
    )
    assert first.status_code == 200
    assert first.headers["etag"] == '"2"'
    assert first.json()["version"] == 2

    stale = await client.patch(
        "/reports/1/sections/executive_summary",
        json={"content": {"text": "Stale"}},
        headers={**auth_headers(), "If-Match": '"1"'},
    )
    assert stale.status_code == 412

    async with SessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(report_section_edits))
    assert count == 1


async def test_viewer_cannot_patch_but_editor_can(client, auth_headers):
    await client.post("/reports/1/shares", json={"target_user_id": 2, "permission": "edit"}, headers=auth_headers())
    await client.post("/reports/1/shares", json={"target_user_id": 3, "permission": "view"}, headers=auth_headers())

    viewer = await client.patch(
        "/reports/1/sections/market_size",
        json={"content": {"value": "$11B"}},
        headers={**auth_headers(user_id=3, org_id=1), "If-Match": '"1"'},
    )
    editor = await client.patch(
        "/reports/1/sections/market_size",
        json={"content": {"value": "$12B"}},
        headers={**auth_headers(user_id=2, org_id=1), "If-Match": '"1"'},
    )
    assert viewer.status_code == 403
    assert editor.status_code == 200


async def test_history_pagination_and_revert(client, auth_headers):
    first = await client.patch(
        "/reports/1/sections/key_trends",
        json={"content": {"items": ["AI"]}},
        headers={**auth_headers(), "If-Match": '"1"'},
    )
    second = await client.patch(
        "/reports/1/sections/key_trends",
        json={"content": {"items": ["AI", "cloud"]}},
        headers={**auth_headers(), "If-Match": '"2"'},
    )
    assert first.status_code == 200
    assert second.status_code == 200

    history = await client.get("/reports/1/sections/key_trends/history?limit=1", headers=auth_headers())
    assert history.status_code == 200
    assert len(history.json()["edits"]) == 1
    assert history.json()["next_cursor"] is not None

    edit_id = history.json()["edits"][0]["id"]
    reverted = await client.post(f"/reports/1/sections/key_trends/revert/{edit_id}", headers=auth_headers())
    assert reverted.status_code == 200
    assert reverted.json()["version"] == 4


async def test_ai_rewrite_success_and_failure(client, auth_headers):
    response = await client.post(
        "/reports/1/sections/executive_summary/ai-rewrite",
        json={"instruction": "make it punchier"},
        headers={**auth_headers(request_id="rid-ai"), "If-Match": '"1"'},
    )
    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert "MAKE IT PUNCHIER" in response.json()["content"]["rewritten"]
    assert llm_client.call_count == 1
    assert llm_client.requests[0]["request_id"] == "rid-ai"

    llm_client.raise_next = RuntimeError("provider down")
    failed = await client.post(
        "/reports/1/sections/market_size/ai-rewrite",
        json={"instruction": "shorter"},
        headers=auth_headers(),
    )
    assert failed.status_code == 502

    async with SessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(report_section_edits))
    assert count == 1

