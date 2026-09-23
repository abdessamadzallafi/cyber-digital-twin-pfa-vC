# PRE-MIGRATION STARTUP FIX

Projet : `/home/abdo/Downloads/CyberPort`
Date : 2026-09-19

## Verdict

```text
STARTUP_FIX_BLOCKED

## Addendum — local startup helper and current mission status

`startup.sh` was also corrected after the initial report: its normal path now
calls `verify_schema()` and verifies the existing `data_lake` directory. It no
longer calls `Base.metadata.create_all()` or `mkdir -p`.

The two DB hashes were rechecked after this edit and remain:

```text
digital_twin.db       22a63de73b40bae184f583b66c40eed122ef5189215f49365449e46242e0b61e
data/digital_twin.db  9d667e0b887988be8c7f2882f3b5595bc8a1720573381ed3fb58d98484ed1d62
```

No SQLite or Data Lake write was performed in this mission. The blocking
`digital_twin.db` change predates this edit and is documented above.

```text
DATABASE_MODIFIED = 0
SCHEMA_MODIFIED = 0
DATA_LAKE_MODIFIED = 0
SQLITE_MIGRATION_EXECUTED = 0
DOCKER_VOLUME_DELETED = 0
```

These values describe this mission's operations only; the pre-existing
unexpected `siem_events` write still prevents the requested runtime-validation
verdict and Docker build.

## Remaining validation gates

The previous source validation recorded `286 passed`; it also recorded the
subsequent unexpected write to `digital_twin.db`. To respect the stop rule,
this mission did not rerun `pytest --collect-only -q`, `pytest -q`, or the
dashboard build. `docker compose config` and `docker compose build` were not
run because the SQLite guard is not cleared. `docker compose up -d --build`
was not run.

Targeted checks completed in this mission:

```text
startup.sh syntax: PASS
startup correction diff check: PASS
PRAGMA integrity_check (digital_twin.db): ok
PRAGMA integrity_check (data/digital_twin.db): ok
```

Global `git diff --check` remains blocked only by pre-existing trailing
whitespace in `backend/network/network_monitor.py` and
`dashboard/src/index.css`, outside this mission's files.
```

La correction du startup a été appliquée et les tests source passent, mais la validation est bloquée par la modification observée de `digital_twin.db` pendant la suite pytest. Conformément à la consigne, aucune reconstruction Docker n’a été exécutée après cette détection.

## 1. Problème identifié

Les anciennes images Docker étaient obsolètes, mais leur reconstruction aurait déclenché des opérations de schéma au démarrage.

Le problème source était double :

1. `backend.database` exécutait des opérations de création/mise à niveau à l’import ;
2. `backend.main` exécutait encore `Base.metadata.create_all()` dans le lifespan FastAPI.

Ainsi, le simple démarrage du backend pouvait effectuer implicitement des opérations assimilables à une migration.

## 2. Chemin exact du startup

```text
Dockerfile backend
  -> CMD ["python", "run.py"]
  -> run.py importe backend.main
  -> backend.main importe backend.database
  -> backend.database/__init__.py était exécuté
  -> Base.metadata.create_all(bind=engine)
  -> _upgrade_legacy_schema()
  -> ALTER TABLE / CREATE INDEX potentiels
  -> FastAPI lifespan
  -> DatabaseBase.metadata.create_all(bind=db_engine)
  -> MQTT / UDP / WebSocket
```

### Appels identifiés

- `run.py:2` : `from backend.main import app`.
- `backend/main.py:16` : import de `backend.database`.
- `backend/database/__init__.py` anciennement ligne 10 : `Base.metadata.create_all(bind=engine)` à l’import.
- `backend/database/__init__.py` anciennement ligne 32 : `_upgrade_legacy_schema()` à l’import.
- `backend/main.py` anciennement lignes 91-96 : `DatabaseBase.metadata.create_all(bind=db_engine)` dans `lifespan()`.
- `backend/database.py:86` : appel legacy `Base.metadata.create_all(bind=engine)`. Ce fichier est une définition ORM legacy non utilisée par les imports runtime canoniques ; il a été restauré inchangé et n’est pas appelé par `run.py -> backend.main`.

## 3. Opérations de modification de schéma découvertes

Dans `backend/database/__init__.py` :

```python
Base.metadata.create_all(bind=engine)
```

Dans `_upgrade_legacy_schema()` :

```sql
ALTER TABLE incidents ADD COLUMN first_seen DATETIME
ALTER TABLE incidents ADD COLUMN last_seen DATETIME
ALTER TABLE incidents ADD COLUMN occurrence_count INTEGER NOT NULL DEFAULT 1
ALTER TABLE incidents ADD COLUMN dedup_key VARCHAR
CREATE INDEX IF NOT EXISTS ix_incidents_dedup_key ON incidents (dedup_key)
CREATE INDEX IF NOT EXISTS ix_incidents_last_seen ON incidents (last_seen)
CREATE INDEX IF NOT EXISTS ix_incidents_first_seen ON incidents (first_seen)
CREATE INDEX IF NOT EXISTS ix_missions_status ON missions (status)
```

Dans `backend/main.py` :

```python
DatabaseBase.metadata.create_all(bind=db_engine)
```

## 4. Correction appliquée

### `backend/database/__init__.py`

- suppression de l’appel `Base.metadata.create_all(bind=engine)` à l’import ;
- suppression de l’appel `_upgrade_legacy_schema()` à l’import ;
- conservation de `_upgrade_legacy_schema()` ;
- ajout de `initialize_schema()` comme opération explicite de setup contrôlé ;
- ajout de `verify_schema(bind=engine)` en lecture, vérifiant uniquement la présence des tables attendues.

`initialize_schema()` contient encore les opérations de création/mise à niveau, mais n’est appelée par aucun chemin de startup normal.

### `backend/main.py`

Le lifespan ne crée plus de tables. Il exécute uniquement :

```python
verify_schema(db_engine)
logger.info("Existing database schema verified")
```

Le runtime normal vérifie donc une base existante au lieu de créer ou modifier son schéma.

### `backend/database.py`

Le fichier legacy a été restauré exactement dans son état initial. Il n’est pas dans le chemin d’import runtime canonique observé (`backend.database` package).

## 5. Fichiers modifiés

Modifiés par cette correction :

- `/home/abdo/Downloads/CyberPort/backend/database/__init__.py`
- `/home/abdo/Downloads/CyberPort/backend/main.py`
- `/home/abdo/Downloads/CyberPort/PRE_MIGRATION_STARTUP_FIX.md`

Non modifiés :

- tests ;
- ML ;
- SIEM ;
- alert semantics ;
- missions ;
- MQTT ;
- dashboard ;
- ORM legacy `backend/database.py` ;
- Docker Compose ;
- Data Lake ;
- SQLite.

Des sauvegardes temporaires des fichiers concernés ont été placées hors dépôt dans :

```text
/tmp/cyberport-startup-fix-backup/
```

Aucune sauvegarde de base SQLite n’a été créée ni modifiée.

## 6. Vérification statique après correction

La recherche dans `backend/` montre maintenant :

- `create_all()` uniquement dans les fonctions explicites ou le fichier legacy historique ;
- `_upgrade_legacy_schema()` uniquement comme définition et appel interne de `initialize_schema()` ;
- `ALTER TABLE` uniquement dans la fonction explicite `_upgrade_legacy_schema()` ;
- `CREATE INDEX` uniquement dans la fonction explicite `_upgrade_legacy_schema()`.

Le chemin `run.py -> backend.main -> backend.database -> lifespan` ne déclenche plus ces opérations.

Les imports suivants ont été exécutés avant les tests :

```text
import backend.database
import backend.main
```

Résultat : `IMPORTS_PASS`.

Les hashes SQLite étaient identiques avant et après ces imports.

## 7. Tests exécutés

### Compilation

```text
python3 -m compileall -q backend
COMPILEALL_PASS
```

### Collecte

```text
pytest --collect-only -q
```

Résultat :

```text
286 tests collected
```

### Suite complète

```text
pytest -q
```

Résultat fonctionnel :

```text
286 passed, 2 warnings in 2.99s
```

Warnings :

- dépréciation Starlette/httpx de `TestClient` ;
- incompatibilité de version SciPy/NumPy déjà présente.

Aucun test n’a été modifié.

### Dashboard

Cette étape n’a pas modifié le dashboard. Le build dashboard précédemment validé reste :

```text
Compiled successfully.
```

## 8. Git diff check

Contrôle ciblé des fichiers de la correction :

```text
git diff --check -- backend/database/__init__.py backend/main.py
```

Résultat : PASS.

Le contrôle global reste en échec sur des espaces de fin préexistants dans :

- `backend/network/network_monitor.py`
- `dashboard/src/index.css`

Ces lignes ne font pas partie de cette correction et n’ont pas été modifiées.

## 9. SHA-256 SQLite avant/après

### Snapshot avant correction et tests

```text
data/digital_twin.db
9d667e0b887988be8c7f2882f3b5595bc8a1720573381ed3fb58d98484ed1d62

 digital_twin.db
711e40b6b4cc2e0d74e2094650523455a90f634011752023395dee5334c0271e
```

### Après import sans écriture

Les deux hashes étaient strictement identiques après import de `backend.database` et `backend.main`.

### Après `pytest -q`

```text
data/digital_twin.db
9d667e0b887988be8c7f2882f3b5595bc8a1720573381ed3fb58d98484ed1d62

 digital_twin.db
22a63de73b40bae184f583b66c40eed122ef5189215f49365449e46242e0b61e
```

### Différence détectée

`data/digital_twin.db` : inchangée.

`digital_twin.db` : modifiée pendant la validation pytest.

Comptages observés pour `digital_twin.db` :

| TABLE | AVANT | APRÈS | DELTA |
|---|---:|---:|---:|
| `sensor_readings` | 11180 | 11180 | 0 |
| `alerts` | 8077 | 8077 | 0 |
| `siem_events` | 43651 | 43663 | +12 |
| `incidents` | 50 | 50 | 0 |
| `missions` | 157 | 157 | 0 |

L’augmentation porte uniquement sur `siem_events`, probablement liée à l’audit HTTP exécuté par l’application pendant les tests `TestClient`. Cette attribution est cohérente avec le code, mais la règle de sécurité de la mission impose de considérer le changement comme bloquant sans le masquer.

Les deux bases restent intégralement valides :

```text
PRAGMA integrity_check = ok
```

## 10. Docker

Étapes non exécutées après la détection de modification DB :

```text
docker compose build
```

Aucun `docker compose up -d` n’a été exécuté.

Raison : stop condition obligatoire après changement de `digital_twin.db`.

La correction statique est prête à être testée dans Docker, mais la reconstruction est volontairement bloquée jusqu’à décision sur l’écriture de `siem_events` pendant les tests.

## 11. Confirmation de sécurité

```text
DATABASE_MODIFIED = 1
SCHEMA_MODIFIED = 0
DATA_LAKE_MODIFIED = 0
MIGRATION_EXECUTED = 0
```

`DATABASE_MODIFIED = 1` signifie qu’une modification a été observée pendant la suite de tests ; aucune modification directe de base n’a été exécutée par la correction startup elle-même.

## Conclusion

La correction startup est techniquement minimale et supprime les opérations implicites de schéma du chemin normal de démarrage. Les tests source passent tous.

La validation finale est bloquée par l’écriture de 12 événements SIEM dans `digital_twin.db` pendant `pytest -q`. Aucune image Docker n’a été reconstruite après ce constat, et aucune migration SQLite n’a été exécutée.

STARTUP_FIX_BLOCKED
