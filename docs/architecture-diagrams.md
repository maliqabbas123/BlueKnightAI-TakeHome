# Architecture Diagrams

This document contains Mermaid diagrams for understanding the project structure, database model, and main runtime flows.

## Architecture

```mermaid
flowchart TB
    Client[API Client / User] -->|Bearer JWT + X-Request-ID| FastAPI[FastAPI App]

    FastAPI --> Middleware[RequestIdMiddleware]
    Middleware --> ContextVar[request_id ContextVar]

    FastAPI --> Routers[routers/ HTTP Layer]
    Routers --> Auth[JWT Auth Dependency]
    Routers --> Services[services/ Business Logic]
    Services --> Repo[repository/ SQL Layer]
    Repo --> DB[(PostgreSQL)]

    Services --> LLMClient[LLMClient Protocol]
    LLMClient --> InMemoryLLM[InMemoryLLMClient Stub]

    Services --> Logs[Structured key=value Logs]
    ContextVar --> Logs
    ContextVar --> LLMClient
```

## Database Model

```mermaid
erDiagram
    users {
        BIGSERIAL id PK
        BIGINT org_id
        TEXT email UK
    }

    market_research_reports {
        BIGSERIAL id PK
        BIGINT user_id
        TEXT company_name
        TEXT company_url
        JSONB sections
        TIMESTAMPTZ created_at
    }

    report_sections {
        BIGSERIAL id PK
        BIGINT report_id FK
        TEXT section_key
        JSONB content
        INT version
        TIMESTAMPTZ updated_at
        BIGINT updated_by_user_id FK
    }

    report_section_edits {
        BIGSERIAL id PK
        BIGINT report_id FK
        TEXT section_key
        INT version_before
        INT version_after
        JSONB content_before
        JSONB content_after
        BIGINT editor_user_id FK
        edit_source source
        TIMESTAMPTZ ts
    }

    report_shares {
        BIGSERIAL id PK
        BIGINT report_id FK
        BIGINT target_user_id FK
        share_permission permission
        BIGINT granted_by_user_id FK
        TIMESTAMPTZ created_at
        TIMESTAMPTZ revoked_at
    }

    users ||--o{ market_research_reports : owns
    market_research_reports ||--o{ report_sections : has
    market_research_reports ||--o{ report_section_edits : audits
    market_research_reports ||--o{ report_shares : shared_as
    users ||--o{ report_sections : updated_by
    users ||--o{ report_section_edits : edits
    users ||--o{ report_shares : target_user
    users ||--o{ report_shares : granted_by
```

## Request Access Flow

```mermaid
flowchart TD
    Start[Incoming Request] --> Token{Valid Bearer JWT?}
    Token -->|No| R401[401 unauthenticated]
    Token -->|Yes| CurrentUser[CurrentUser user_id + org_id]

    CurrentUser --> LoadAccess[Load report + active share for current user]
    LoadAccess --> ReportExists{Report exists?}
    ReportExists -->|No| R404[404 not found]
    ReportExists -->|Yes| RoleCheck[Compute owner/editor/viewer]

    RoleCheck --> EndpointType{Endpoint type}

    EndpointType -->|Shares CRUD| OwnerOnly{Owner?}
    OwnerOnly -->|No| R403A[403 forbidden]
    OwnerOnly -->|Yes| AllowShares[Allow]

    EndpointType -->|Patch/Revert/AI Rewrite| EditAccess{Owner or editor?}
    EditAccess -->|No| R403B[403 forbidden]
    EditAccess -->|Yes| AllowWrite[Allow]

    EndpointType -->|Read Report/Section/History| AnyAccess{Owner/editor/viewer?}
    AnyAccess -->|No| R403C[403 forbidden]
    AnyAccess -->|Yes| AllowRead[Allow]
```

## Section Patch Flow

```mermaid
sequenceDiagram
    participant Client
    participant Router
    participant Service
    participant Repository
    participant DB as PostgreSQL
    participant Log as Logger

    Client->>Router: PATCH /reports/{id}/sections/{key}<br/>If-Match: "1"<br/>{content}
    Router->>Service: load_access(report_id, current_user)
    Service->>Repository: get_report_access()
    Repository->>DB: SELECT report + active share
    DB-->>Repository: access row
    Repository-->>Service: owner/editor/viewer

    Service->>Service: require owner or editor
    Service->>Service: parse If-Match version

    Service->>Repository: update_section_with_audit(expected_version=1)
    Repository->>DB: WITH old_section AS (...), updated_section AS (UPDATE ... WHERE version = 1 RETURNING ...), inserted_edit AS (INSERT audit SELECT ...)
    alt Version matches
        DB-->>Repository: new version + content
        Repository-->>Service: version=2, content
        Service->>DB: COMMIT
        Service->>Log: request_id user_id report_id section_key version action
        Service-->>Router: updated section
        Router-->>Client: 200 OK + ETag: "2"
    else Version stale
        DB-->>Repository: no rows
        Repository-->>Service: None
        Service->>DB: COMMIT
        Service-->>Router: PreconditionFailed
        Router-->>Client: 412 structured error
    end
```

## AI Rewrite Flow

```mermaid
sequenceDiagram
    participant Client
    participant Router
    participant Service
    participant Repo as Repository
    participant LLM as LLMClient
    participant DB as PostgreSQL

    Client->>Router: POST /reports/{id}/sections/{key}/ai-rewrite<br/>{instruction}
    Router->>Service: ai_rewrite_section()
    Service->>Repo: get_report_access()
    Repo->>DB: SELECT report + active share
    DB-->>Repo: access row
    Service->>Service: require owner or editor

    Service->>Repo: get_section()
    Repo->>DB: SELECT current section/version
    DB-->>Repo: content + version

    Service->>LLM: call(operation, request_id, messages)
    alt LLM succeeds
        LLM-->>Service: rewritten content
        Service->>Repo: update_section_with_audit(source=ai_rewrite)
        Repo->>DB: UPDATE with version predicate + INSERT audit
        DB-->>Repo: new version + content
        Service->>DB: COMMIT
        Service-->>Router: version + content
        Router-->>Client: 200 OK
    else LLM raises
        LLM-->>Service: exception
        Service-->>Router: UpstreamError
        Router-->>Client: 502 structured error
        Note over DB: No rows written
    end
```

## Migration / Backfill Flow

```mermaid
flowchart TD
    Start[Alembic upgrade head] --> Types[Create enum types<br/>edit_source, share_permission]
    Types --> BaseTables[Create base tables if missing<br/>users, market_research_reports]
    BaseTables --> NewTables[Create collaboration tables<br/>report_sections, report_section_edits, report_shares]
    NewTables --> Indexes[Create indexes<br/>history index + active share partial unique index]
    Indexes --> Backfill[Backfill report_sections from<br/>market_research_reports.sections JSONB]
    Backfill --> Conflict[ON CONFLICT report_id, section_key DO NOTHING]
    Conflict --> Done[Migration complete]

    Downgrade[Alembic downgrade base] --> DropIndexes[Drop indexes if exists]
    DropIndexes --> DropTables[Drop three collaboration tables]
    DropTables --> DropEnums[Drop enum types]
```

## Revert Flow

```mermaid
sequenceDiagram
    participant Client
    participant Service
    participant Repo
    participant DB

    Client->>Service: POST revert/{edit_id}
    Service->>Repo: get_edit(report_id, section_key, edit_id)
    Repo->>DB: SELECT target historical edit
    DB-->>Repo: content_before from selected edit

    Service->>Repo: get_section(report_id, section_key)
    Repo->>DB: SELECT current version
    DB-->>Repo: current version

    Service->>Repo: update_section_with_audit(source=revert, content_after=target.content_before)
    Repo->>DB: UPDATE current section + INSERT new audit row

    DB-->>Repo: new version/content
    Service-->>Client: 200 {version, content}

    Note over DB: Historical edit rows are never mutated or deleted
```

