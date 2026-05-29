# BlueKnight MRR Collaboration Backend

FastAPI backend for collaborative market research report sections: report sharing, section edits with optimistic concurrency, history, revert, and AI-assisted rewrite through a swappable LLM client.

For visual architecture and flow diagrams, see [docs/architecture-diagrams.md](docs/architecture-diagrams.md).

## Requirements

- Python 3.12+
- PostgreSQL 14+ running locally
- `createdb` and `psql` available on your `PATH`

The app is intentionally Docker-free for this take-home. It expects a normal local PostgreSQL database and uses Alembic for schema management.

## Local setup

Create and activate a virtual environment:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m ensurepip --upgrade
python -m pip install -e ".[dev]"
```

Create a local environment file:

```bash
cp .env.example .env
```

Edit `.env` if your database user/password differs. For passwordless local Postgres using your OS user, this is usually enough:

```env
DATABASE_URL=postgresql+asyncpg://YOUR_OS_USER@localhost:5432/blueknight
JWT_SECRET=dev-secret
JWT_ALGORITHM=HS256
LOG_LEVEL=INFO
```

For username/password auth, use:

```env
DATABASE_URL=postgresql+asyncpg://blueknight:blueknight@localhost:5432/blueknight
```

Create the development database:

```bash
createdb blueknight
```

If `createdb` fails because PostgreSQL is not running, start your local cluster first, for example:

```bash
sudo pg_ctlcluster 16 main start
```

Run migrations and seed sample data:

```bash
alembic upgrade head
python scripts/seed.py
```

Start the API:

```bash
uvicorn app.main:app --reload
```

The API will be available at:

```text
http://127.0.0.1:8000
```

Interactive OpenAPI docs:

```text
http://127.0.0.1:8000/docs
```

## Environment variables

| Name | Required | Default | Purpose |
| --- | --- | --- | --- |
| `DATABASE_URL` | Yes | local `blueknight` URL | Async SQLAlchemy/PostgreSQL connection string. |
| `JWT_SECRET` | Yes | `dev-secret` | HS256 secret used to decode bearer tokens. |
| `JWT_ALGORITHM` | No | `HS256` | JWT signing algorithm. |
| `LOG_LEVEL` | No | `INFO` | Python logging level. |

## Manual auth token

The project does not implement JWT issuance, as requested. For manual testing, generate a token with the helper:

```bash
. .venv/bin/activate
python -c "from app.auth import create_test_token; print(create_test_token(1, 1))"
```

Use the token in API calls:

```bash
TOKEN="$(python -c "from app.auth import create_test_token; print(create_test_token(1, 1))")"
curl -H "Authorization: Bearer $TOKEN" \
  -H "X-Request-ID: demo-1" \
  http://127.0.0.1:8000/reports/1
```

Read a section and capture its ETag:

```bash
curl -i -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/reports/1/sections/executive_summary
```

Patch a section with optimistic concurrency:

```bash
curl -X PATCH \
  -H "Authorization: Bearer $TOKEN" \
  -H 'If-Match: "1"' \
  -H "Content-Type: application/json" \
  -d '{"content":{"text":"Updated executive summary"}}' \
  http://127.0.0.1:8000/reports/1/sections/executive_summary
```

## Tests

Tests are written for real PostgreSQL because the task relies on JSONB, enum types, partial indexes, and update concurrency semantics.

Create a separate test database:

```bash
createdb blueknight_test
```

Run tests:

```bash
export DATABASE_URL=postgresql+asyncpg://$USER@localhost:5432/blueknight_test
export JWT_SECRET=test-secret
pytest
```

The test fixture recreates the schema and seeds:

- 2 organisations
- 3 users per organisation
- 1 report owned by `user_id = 1`
- 3 report sections

## Useful commands

```bash
# Show migration history
alembic history

# Apply migrations
alembic upgrade head

# Roll back the one migration
alembic downgrade base

# Reseed the development database
python scripts/seed.py

# Run only API tests
pytest tests/test_api.py
```

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
