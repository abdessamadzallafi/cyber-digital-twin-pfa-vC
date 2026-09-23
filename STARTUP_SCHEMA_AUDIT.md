# Startup schema audit

## Findings

| File | Function / statement | Caller | Execution point | SQLite operation | Risk | Minimal correction |
| --- | --- | --- | --- | --- | --- | --- |
| `backend/database/__init__.py` | `Base.metadata.create_all(bind=engine)` | Import of `backend.database` | Previously at module import during `run.py -> backend.main` | Create missing tables/indexes | Import altered runtime DB | Keep only in explicit `initialize_schema()` |
| `backend/database/__init__.py` | `_upgrade_legacy_schema()` | Previously module import; now only `initialize_schema()` | Previously at module import | `ALTER TABLE incidents ADD COLUMN ...`; `CREATE INDEX ...` | Startup changed schema/indexes | Retain as explicit setup only |
| `backend/main.py` | `DatabaseBase.metadata.create_all(bind=db_engine)` | FastAPI lifespan | Previously every backend startup | Create missing tables/indexes | Docker startup altered schema | Replace with `verify_schema(db_engine)` |
| `startup.sh` | Inline `Base.metadata.create_all(bind=engine)` | `./startup.sh` | Before launch choice | Create missing tables/indexes | Local start helper altered schema | Use `verify_schema()` only |
| `backend/database.py` | `Base.metadata.create_all(bind=engine)` | No active canonical caller found | Independent legacy module import | Create legacy tables/indexes | Potential only if explicitly imported | Leave untouched; outside Docker path |
| `test_setup.sh` | `Base.metadata.create_all(bind=engine)` | Explicit setup script | Script invocation | Create tables/indexes | Intended setup mutation | Leave explicit operation unchanged |
| Tests | `Base.metadata.create_all(engine)` | Individual tests | In-memory test setup | In-memory table creation | No project DB schema operation | Leave unchanged |

## Docker path

`backend/Dockerfile` runs `python run.py`. `run.py` imports `backend.main`,
which imports the canonical `backend.database` package. The FastAPI lifespan
runs before serving requests. The corrected normal path reaches only
`verify_schema()`, which inspects existing required tables. It does not call
`create_all`, `_upgrade_legacy_schema`, `ALTER TABLE`, or `CREATE INDEX`.

`backend.database.initialize_schema()` retains creation and legacy upgrade as
an explicit, separate preparation operation. No normal Docker, FastAPI, or
`startup.sh` caller invokes it.
