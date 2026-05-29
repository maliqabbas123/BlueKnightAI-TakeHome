import asyncio

from sqlalchemy import delete, insert

from app.database import SessionLocal
from app.models.schema import market_research_reports, report_section_edits, report_sections, report_shares, users


async def main() -> None:
    async with SessionLocal() as session:
        await session.execute(delete(report_section_edits))
        await session.execute(delete(report_shares))
        await session.execute(delete(report_sections))
        await session.execute(delete(market_research_reports))
        await session.execute(delete(users))
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


if __name__ == "__main__":
    asyncio.run(main())

