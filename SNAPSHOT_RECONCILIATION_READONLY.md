# Snapshot reconciliation — read only

## Verdict

```text
SNAPSHOT_RECONCILIATION_EXPLAINED
```

Niveau de certitude : élevé. L'écart de hash de `digital_twin.db` provient de lignes SIEM ajoutées après le snapshot, pas d'une corruption, migration ou simple variation de représentation binaire SQLite.

## Empreintes et métadonnées

| Fichier | SHA-256 | Taille | mtime | inode |
| --- | --- | ---: | --- | ---: |
| `digital_twin.db` actuel | `22a63de73b40bae184f583b66c40eed122ef5189215f49365449e46242e0b61e` | 15 400 960 | `2026-09-19 17:25:49.472734977 +0100` | 2155750 |
| Hash historique attendu | `711e40b6b4cc2e0d74e2094650523455a90f634011752023395dee5334c0271e` | fichier absent | snapshot antérieur | n/a |
| Backup A | `b425fab03fd5f72eb8d253166817705d29d51c9e3f7862449a16a4bbd89ed9ad` | 15 392 768 | `2026-09-19 13:27:32.399887210 +0100` | 2156212 |
| `data/digital_twin.db` actuel | `9d667e0b887988be8c7f2882f3b5595bc8a1720573381ed3fb58d98484ed1d62` | 43 442 176 | `2026-09-19 17:17:15.115384014 +0100` | 2155896 |
| Backup B | `195c40827d2ee6c0e6f5aa634a8d3ae997db214baa85858b2a85e130add58c1c` | 43 421 696 | `2026-09-19 13:27:32.451887918 +0100` | 2156246 |

Aucun fichier WAL, SHM ou journal SQLite n'a été trouvé pour les fichiers courants ou les backups observés.

## Intégrité et schéma

Les quatre fichiers ont été ouverts avec `mode=ro&immutable=1` uniquement.

```text
PRAGMA integrity_check = ok
PRAGMA user_version = 0
PRAGMA journal_mode = delete
```

Le digest `sqlite_master` est identique : `8f58b9d829b6714ab6288d14829c3b3ff78e4250cce7a7bc3a945198a7e529ad`. Les tables, indexes, vues et triggers sont donc inchangés.

## Comparaison avec backup A

La base courante est différente du backup A et plus grande de 8 192 octets. Toutes les tables sauf `siem_events` sont identiques ligne par ligne : `alerts` (8 077), `incidents` (50), `missions` (157), `sensor_readings` (11 180), et les tables vides.

| Base | siem_events | max(id) | occurred_at max |
| --- | ---: | ---: | --- |
| Backup A | 43 639 | 43 639 | `2026-09-09 15:17:55.518086` |
| Actuelle | 43 663 | 43 663 | `2026-09-19 16:25:49.471675` |

La comparaison complète des lignes donne 24 ajouts et 0 suppression. Les IDs 43640 à 43651, datés `2026-09-19 16:12:25` à `16:12:26`, sont des événements `auth/login_success` et `http/http_request`. Les IDs 43652 à 43663, datés `16:25:48` à `16:25:49`, sont de même nature et couvrent `/token`, `/api/v1/ai/predict` et `/api/v1/siem/reports`.

Les rapports `PRE_MIGRATION_STARTUP_FIX.md` et `FINAL_INTEGRATION_VALIDATION.md` placent le hash historique attendu au palier de 43 651 événements, après les 12 premiers ajouts. Les 12 événements suivants expliquent le hash actuel. Le middleware d'audit HTTP et l'audit d'authentification correspondent directement à ces enregistrements.

## Comparaison avec backup B

La DB A actuelle n'est ni le backup B ni une variation binaire de celui-ci : elle est l'autre historique SQLite. Même schéma, mais `alerts` vaut 8 077 contre 47 675, `incidents` 50 contre 74, `missions` 157 contre 35, `sensor_readings` 11 180 contre 29 069 et `siem_events` 43 663 contre 111 545.

`data/digital_twin.db` est, indépendamment, une suite append-only de backup B : 19 alerts, 2 incidents, 3 sensor readings et 36 siem_events ajoutés, sans suppression ni changement de schéma. Cela n'implique aucune fusion des deux historiques.

## Chronologie et limite de preuve

Le backup A date du `2026-09-19 13:27:32 +0100`; les 24 ajouts de la DB A sont à `16:12` puis `16:25` le même jour. Les IDs, timestamps, routes et types d'événement concordent avec les validations applicatives documentées.

Le fichier binaire du hash historique `711e...` n'est pas disponible : une comparaison octet-à-octet directe est donc impossible. Les différences logiques sont néanmoins complètement identifiées, avec schéma identique et aucune suppression.

```text
DATABASE_MODIFIED = 0
SCHEMA_MODIFIED = 0
DATA_LAKE_MODIFIED = 0
MIGRATION_EXECUTED = 0
```
