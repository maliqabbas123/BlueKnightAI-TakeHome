import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+asyncpg://blueknight:blueknight@localhost:5432/blueknight_test",
)
os.environ.setdefault("JWT_SECRET", "test-secret")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert

from app.auth import create_test_token
from app.database import SessionLocal, engine, metadata
from app.llm_client import llm_client
from app.main import app
from app.models.schema import market_research_reports, report_section_edits, report_sections, report_shares, users


@pytest.fixture
def token_for():
    def _make(user_id: int, org_id: int) -> str:
        return create_test_token(user_id, org_id)

    return _make


@pytest.fixture
def auth_headers(token_for):
    def _headers(user_id: int = 1, org_id: int = 1, request_id: str = "test-request-id"):
        return {"Authorization": f"Bearer {token_for(user_id, org_id)}", "X-Request-ID": request_id}

    return _headers


@pytest_asyncio.fixture(autouse=True)
async def seed_db():
    llm_client.call_count = 0
    llm_client.raise_next = None
    llm_client.requests.clear()
    async with engine.begin() as conn:
        await conn.run_sync(metadata.drop_all)
        await conn.run_sync(metadata.create_all)
    async with SessionLocal() as session:
        await session.execute(
            insert(users),
            [
                {"id": 1, "org_id": 1, "email": "owner@org1.test"},
                {"id": 2, "org_id": 1, "email": "editor@org1.test"},
                {"id": 3, "org_id": 1, "email": "viewer@org1.test"},
                {"id": 4, "org_id": 2, "email": "owner@org2.test"},
                {"id": 5, "org_id": 2, "email": "editor@org2.test"},
                {"id": 6, "org_id": 2, "email": "viewer@org2.test"},
            ],
        )
        sections = {
            "executive_summary": {"text": "Initial summary"},
            "market_size": {"value": "$10B"},
            "key_trends": {"items": ["AI", "automation"]},
        }
        await session.execute(
            insert(market_research_reports),
            [
                {
                    "id": 1,
                    "user_id": 1,
                    "company_name": "Acme AI",
                    "company_url": "https://example.com",
                    "sections": sections,
                }
            ],
        )
        for key, content in sections.items():
            await session.execute(
                insert(report_sections).values(
                    report_id=1,
                    section_key=key,
                    content=content,
                    version=1,
                    updated_by_user_id=1,
                )
            )
        await session.commit()
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
