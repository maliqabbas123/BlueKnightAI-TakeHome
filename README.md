# BlueKnight MRR Collaboration Backend

FastAPI backend for collaborative market research report sections: report sharing, section edits with optimistic concurrency, history, revert, and AI-assisted rewrite through a swappable LLM client.

## Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m ensurepip --upgrade
python -m pip install -e ".[dev]"
createdb blueknight
createdb blueknight_test
export DATABASE_URL=postgresql+asyncpg://$USER@localhost:5432/blueknight
export JWT_SECRET=dev-secret
alembic upgrade head
python scripts/seed.py
uvicorn app.main:app --reload
```

Run tests against PostgreSQL:

```bash
export DATABASE_URL=postgresql+asyncpg://$USER@localhost:5432/blueknight_test
export JWT_SECRET=test-secret
pytest
```

If your local database uses a password, put the full asyncpg URL in `DATABASE_URL`.

## Schema overview

The base tables are `users` and `market_research_reports`. Reports still keep the original `sections` JSONB blob, while editable content is backfilled into `report_sections` as one row per `(report_id, section_key)`.

`report_shares` stores active and revoked shares. A partial unique index on `(report_id, target_user_id) WHERE revoked_at IS NULL` prevents duplicate active shares while preserving old revocation history.

`report_section_edits` is the append-only audit log. Every human edit, AI rewrite, and revert writes before/after JSONB content, before/after versions, editor, source, and timestamp.

## Design notes

Auth is intentionally small: every request requires `Authorization: Bearer <jwt>`, decoded with HS256 using `JWT_SECRET`. The token supplies `user_id` and `org_id`; report access is computed at the router boundary and then passed into services. Owners manage shares, owners/editors write sections, and viewers can only read. Cross-organisation sharing is rejected before insert.

Concurrency is section-level and uses ETags. Reads return `ETag: "<version>"`; `PATCH` requires `If-Match`. The write path uses one SQL statement with CTEs: it captures the old row, updates only when `version = expected_version`, and inserts the audit row from the update result. If no row is updated, the API returns `412`.

The audit table is the version history. Revert appends a new `revert` edit whose new content equals the selected edit's `content_before`; historical rows are never mutated. AI rewriting is isolated behind `LLMClient`; the in-memory implementation is deterministic, records calls, and can raise for tests. Provider failures return `502` before any write occurs.

Logging uses Python `logging` with `key=value` structured lines because it is readable locally and easy to parse centrally. Every write includes `request_id`, `user_id`, `report_id`, action/source, and section/version where applicable. Request IDs come from `X-Request-ID` or a generated UUID4 and are also passed into the LLM client.

## What I would do next

- Add OpenAPI examples for the main edit/share flows.
- Add a production LLM provider adapter outside the route/service layers.
- Add service-level metrics for write conflicts, LLM failures, and edit latency.
- Add CI that provisions PostgreSQL and runs Alembic upgrade/downgrade plus pytest.

## Screen recording outline

1. Run `alembic upgrade head` and `pytest`.
2. Show the three-layer layout and migration.
3. Demo ETag read, successful patch, stale patch returning `412`.
4. Demo history, revert, and AI rewrite with request-id propagation.

