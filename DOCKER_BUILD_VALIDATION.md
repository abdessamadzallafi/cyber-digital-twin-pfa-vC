# Docker Build Validation

## Verdict

```text
DOCKER_BUILD_READY_FOR_RUNTIME
```

| COMPONENT | TEST | RESULT | EVIDENCE | ISSUE |
| --- | --- | --- | --- | --- |
| Backend | `python3 -m compileall -q backend` | PASS | Command completed successfully | None |
| Source | `pytest --collect-only -q` | PASS | 286 tests collected | Local MQTT socket required unsandboxed execution |
| Source | `pytest -q` | PASS | 286 passed, 2 existing warnings | None |
| Dashboard | `npm run build` | PASS | Production build compiled | None |
| Compose | `docker compose config` | PASS | Resolved configuration valid | Obsolete `version` warning only |
| Docker | `docker compose build` | PASS | New backend and dashboard images present | No container started |
| SQLite | Integrity | PASS | `PRAGMA integrity_check = ok` on both DBs | None |
| SQLite | Hashes | EXPECTED | A gained 12 pytest HTTP/auth SIEM audit rows; B unchanged | No schema change or deletion |
| Backend image | PATCH3B/PATCH4B/startup | PASS | Layer files equal workspace SHA-256 | None |
| Dashboard image | Current frontend | PASS | Final layer contains `app/src/App.jsx` and `app/src/realtime.js` | None |

## Image IDs

```text
cyberport-backend:latest
sha256:fdae107546bf3d306a1ebe4590ccf1b2327ae73d6c929387a113951f37fd099f
created 2026-09-20T12:18:01.760413146Z
command ["python", "run.py"]

cyberport-dashboard:latest
sha256:67bb6e5dfeabc208994195e8a78103cbcd0f1cc0522fdae29b7432452992a83b
created 2026-09-20T12:18:35.901463431Z
command ["npm", "start"]
```

## Database state

```text
digital_twin.db       a347df2000961d54484e00af43e29638cc4394058d6e6bcdf3ffd71c579d08db
data/digital_twin.db  9d667e0b887988be8c7f2882f3b5595bc8a1720573381ed3fb58d98484ed1d62
integrity_check       ok / ok
```

The targeted cleanup ran only `docker builder prune -f` and reclaimed 1.345GB
of unused build cache. It did not delete images, containers, volumes, SQLite
files, Data Lake files, backups, or working-copy content. Both new images were
verified after cleanup. No Docker service was started, stopped, recreated, or
removed.

```text
DATABASE_MIGRATION_EXECUTED = 0
DATA_DELETION = 0
DATA_LAKE_MODIFIED = 0
DOCKER_VOLUMES_DELETED = 0
```
