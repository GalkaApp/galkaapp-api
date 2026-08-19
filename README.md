# TodoApi

Sync backend for the Todo app (SwiftUI multiplatform client in `../TodoAp`).

**Stack:** FastAPI · SQLAlchemy 2 (async) · PostgreSQL (asyncpg) · Redis pub/sub · SSE (sse-starlette).
FastAPI was chosen over Django because the realtime channel (SSE + pub/sub fan-out) is the
one non-trivial part of a sync server, and that is exactly where async-first frameworks shine.

## Run

Uses the already-running docker-compose infra (Postgres `localhost:5432`, Redis `localhost:6379`);
the `todoapi` database is created inside the running Postgres instance.

```bash
cd TodoApi
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8600
```

Tests (self-contained: in-memory SQLite + in-memory bus, no infra needed):

```bash
.venv/bin/pytest
```

## Sync protocol

Every record carries a client-generated `uuid` (matches the `uuid` field of the SwiftData
models) and a client-set `updated_at` used as the conflict clock. Deletes are tombstones
(`deleted: true`). The server keeps a **per-user monotonically increasing `seq`**; each
applied change gets a new seq, and clients keep the last seq they have seen as their cursor.

| Endpoint | What it does |
| --- | --- |
| `POST /auth/register` | `{email, password, device_name}` → `{token, email, seq}` |
| `POST /auth/login` | same shape; a token per device |
| `POST /auth/logout` | revokes the bearer token |
| `GET /sync?since=N` | delta pull: all projects/tasks (incl. tombstones) with `seq > N`, plus current `seq` |
| `POST /sync` | batch push `{projects: [], tasks: []}`; LWW on `updated_at`; returns `{seq, applied, conflicts}` — `conflicts` holds the newer server rows the client must take |
| `GET /events` | SSE stream; emits `event: sync`, `data: {"seq": N, "origin": "<X-Device-Id>"}` after each push |
| `GET /trash` | tasks with a non-null `trashed_at` and no tombstone, newest first |
| `POST /trash/empty` | tombstones every trashed task and writes a `trash_emptied` log entry |
| `GET /logs?limit=&action=` | activity history, newest first |

Client loop per device:

1. On launch/reconnect: `GET /sync?since=<cursor>` → apply, store new `seq` as cursor.
2. On local change: `POST /sync` with the changed records (send `X-Device-Id`); apply
   `conflicts` back into the local store; cursor = returned `seq`.
3. Keep `GET /events` open (URLSession streaming). On an event whose `origin` differs
   from this device: pull the delta as in step 1.

Datetimes are ISO-8601; anything with an offset is normalized to UTC, and clients must
send **millisecond precision** — with whole seconds a write made in the same second as a
server-side one (recurrence rolls stamp `updated_at + 1 ms`) loses the LWW comparison and
gets rejected. `priority` is 0–3 matching the client enum; `project_uuid` is a loose
reference (no FK) so batches can arrive in any order.

### Trash and logs

Deleting a task is two steps. `trashed_at` marks it as "in the Trash": it syncs like any
other field, so restoring is a plain update and every device agrees on what is trashed.
`deleted` is still the real tombstone, set when a task is purged from the Trash.

`logs` is an append-only activity table synced through the same push/pull. Clients write
the entries for user actions; the server writes its own for the things it does on its
own — rolling a repeating task forward (`repeated`) and emptying the Trash
(`trash_emptied`) — so the history is identical on every device.

## Swift type generation

Client model types are generated from the OpenAPI schema — do not write API DTOs by hand
in the Swift app:

```bash
make swift-types   # writes ../TodoAp/Galka/Api/ApiTypes.swift
```

Emits one Codable struct per Pydantic schema (camelCase + CodingKeys, UUID/Date mapping),
`ApiRoutes` path constants, and `TodoApiJSON.encoder/decoder` matching the server's
datetime format. Rerun after any schema change; the Xcode project picks the file up
automatically. (`make openapi-json` dumps the raw spec for other tooling.)

## Admin

Server-rendered HTML (Jinja2, no SPA) at `/admin` — users overview and a per-user page
with projects, tasks and device tokens. HTTP Basic auth, credentials in `Settings`
(`TODOAPI_ADMIN_USERNAME` / `TODOAPI_ADMIN_PASSWORD`, default `admin`/`admin`).
Excluded from the OpenAPI schema, so it never leaks into the generated Swift types.

## Layout

```
app/
├── main.py        app factory (tests inject SQLite + in-memory bus)
├── config.py      Settings (env prefix TODOAPI_)
├── db.py          Database: engine + session factory
├── models.py      User, AuthToken, Project, Tag, Task, LogEntry (naive-UTC datetimes)
├── schemas.py     Pydantic DTOs
├── security.py    bcrypt hashing, token generation
├── deps.py        session + bearer-token dependencies
├── events.py      EventBus: Redis pub/sub (prod) / in-memory (tests)
├── services/      AuthService, SyncService (seq allocation, LWW upserts), TrashService, LogService
└── routers/       /auth, /sync, /events, /trash, /logs
```

Notes: schema is created on startup (`create_all`) — introduce Alembic before the first
breaking schema change. Tokens are opaque and revocable (one per device login).
