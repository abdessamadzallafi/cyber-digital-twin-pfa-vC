# Final runtime validation — pre-migration SQLite (read-only)

## A. Date/heure de validation

- Date : 2026-09-20, 14:58 UTC
- Mode : strictement lecture seule.
- Méthode : inspection Docker, comparaison de fichiers runtime, SQLite avec URI `mode=ro`, contrôle du workspace et réutilisation des preuves runtime déjà capturées par les validations précédentes.
- Aucun appel HTTP, connexion WebSocket ou publication MQTT n'a été rejoué : dans ce runtime, le middleware d'audit HTTP et le listener MQTT peuvent persister des événements SIEM/telemetry. Les rejouer contredirait `DATABASE_MODIFIED = 0`.

## B. Runtime Docker utilisé

| Service | Conteneur / image | État observé |
|---|---|---|
| Backend | `cyberport-backend-1` / `cyberport-backend@sha256:fdae107546bf3d306a1ebe4590ccf1b2327ae73d6c929387a113951f37fd099f` | running depuis 2026-09-20 13:20 UTC |
| Dashboard | `cyberport-dashboard-1` / `cyberport-dashboard` | running |
| MQTT | `cyberport-mosquitto-1` / `eclipse-mosquitto:2` | running |

Le backend ne monte pas le code hôte : seuls `/app/data` et `/app/reports` sont bind-mounted. Comparaison octet à octet réussie entre l'image runtime et le workspace pour `mqtt_listener`, `siem/managers`, `siem/platform`, `action_dispatcher`, `network_monitor`, `decision_engine` et `events/normalizer`.

## C. Tests API

| Vérification | Résultat | Preuve / limite |
|---|---|---|
| `/health` | PASS — preuve précédente | Confirmation utilisateur : OK. Non rejoué pour préserver DB=0. |
| `/api/v1/platform/health` | PASS — preuve précédente | Confirmation utilisateur : operational. Non rejoué. |
| API protégées avec JWT | PASS — preuve précédente | JWT REST déjà validé. Non rejoué car la requête produirait un audit HTTP SIEM. |
| Rejet sans JWT | PASS — preuve précédente | JWT REST déjà validé. |
| CORS | PASS — preuve précédente | CORS déjà validé. Non rejoué car OPTIONS traverse le middleware HTTP. |
| WebSocket sans JWT | PASS — preuve précédente | Rejet confirmé dans le contexte fourni. Non rejoué. |
| WebSocket avec JWT | PASS — preuve précédente | Acceptation confirmée dans le contexte fourni. Non rejoué. |

Les routes et les appels dashboard existent dans le runtime comparé (`/statistics`, `/devices`, `/incidents`, `/missions`, `/drone/status`, `/api/v1/datalake`, `/ml/anomalies`, `/security/events`).

## D. Tests MQTT

La connexion et l'abonnement du probe ont déjà donné `PASS` après son adaptation Paho. Cette validation ne republie aucun message MQTT.

| Vérification | Résultat | Preuve persistée, lue en mode read-only |
|---|---|---|
| Broker / backend opérationnels | PASS | services Mosquitto et backend `running` ; preuves précédentes `/health` MQTT connected / platform health online |
| Sensor publish atteint backend | PASS — preuve précédente | Deux devices issus du probe possèdent chacun 50 `sensor_readings` dans la DB runtime. |
| Persistence telemetry | PASS | `stress_1789915013` et `stress_1789915091` : 50 readings chacun. |
| Nouvelle publication pendant cet audit | NOT CAPTURED | volontairement interdite par le mode read-only. |

## E. Tests ML

Les données runtime des deux scénarios existants montrent une détection ML réelle : pour chaque device stress, `292 siem_events` de type `sensor/ml_anomaly` et `31 correlation_id` ML distincts sont conservés. Les messages comprennent les modèles scalar temperature, multi-domaines et réseau.

La distinction ML/cyber est observée : l'incident associé est unique, avec `anomaly_type=network_attack`, parce que le scénario contient aussi des signaux sécurité/réseau ; il n'y a pas de second incident `ml_anomaly` créé par le chemin MQTT. Cela correspond à `SmartPortSiem.collect(..., manage_incident=False)` puis au `ActionDispatcher` uniquement lorsque le trigger de sécurité est présent.

Résultat : PASS — preuve runtime existante, relue sans écriture.

## F. Tests sécurité

Pour chacun des deux scenarios de 50 messages, le runtime conserve les catégories demandées :

| source | event_type | SIEM events | correlation_id distincts |
|---|---|---:|---:|
| network | `network_flood` | 30 | 30 |
| network | `unknown_ip` | 50 | 2 |
| sensor | `unknown_device` | 50 | 2 |
| sensor | `ml_anomaly` | 292 | 31 |

Chaîne confirmée : `MQTT -> normalisation -> process_network_data + make_decision -> SmartPortSiem -> AlertManager -> ActionDispatcher/Incident`. Les 50 messages provoquent volontairement plusieurs familles de détection ; elles ne sont pas toutes la même détection répétée.

Résultat : PASS — preuve runtime existante, relue sans écriture.

## G. Tests Alert/SIEM

PATCH3C reste confirmé par les lignes runtime actuelles :

| Device | Alerts | SIEM events | correlation_id distincts |
|---|---:|---:|---:|
| `stress_1789915013` | 65 | 422 | 65 |
| `stress_1789915091` | 65 | 422 | 65 |

La règle Patch 3B est bien présente dans le runtime :

```text
source | device_id | event_type | bucket de 5 secondes | message normalisé
```

`SmartPortSiem.collect` conserve chaque événement SIEM comme evidence. `AlertManager` déduplique uniquement les alertes ayant la même clé fonctionnelle. Les 30 messages `network_flood` portent des compteurs différents (21 à 50), et les scores/domaines ML ainsi que les buckets de cinq secondes créent les autres clés distinctes. Les `422` événements SIEM ne sont donc pas qualifiés de doublons par défaut.

Résultat : PASS — `alerts == correlation_id distincts`; PATCH3C `ROOT_CAUSE_CONFIRMED`.

## H. Tests incidents

| Device | Incidents | occurrence_count |
|---|---:|---:|
| `stress_1789915013` | 1 | 50 |
| `stress_1789915091` | 1 | 50 |

Il n'y a pas d'explosion d'incidents : les 50 messages du même scénario mettent à jour l'incident `network_attack` unique.

Résultat : PASS.

## I. Tests drone

| Vérification | Résultat | Preuve / limite |
|---|---|---|
| Compatibilité probe / Paho local | PASS | Paho local `1.5.1`, sans `CallbackAPIVersion`; `scripts/drone_pipeline_probe.py` contient le fallback 1.x et l'attente `is_published()` bornée. |
| MQTT drone, mission et lifecycle pendant cet audit | NOT CAPTURED | le probe publie une mission et 50 messages stress ; son exécution est incompatible avec le mandat DB=0. |
| Contrat WebSocket `drone_telemetry` et JWT | PASS — preuve précédente | confirmation utilisateur : WebSocket JWT accepté et contrat drone_telemetry PASS. Non rejoué. |
| Champs `position`, `battery`, `mission_id`, `drone_id`, `status`, `timestamp` | PASS — preuve précédente / contrat runtime | le contrat source/runtime comparé les produit dans `_drone_dashboard_payload`; aucune nouvelle télémétrie n'a été émise pour les recapturer. |
| Changement de statut de mission | NOT CAPTURED | nécessite une mission MQTT ; non exécutée. |
| `/drone/status` live pendant cet audit | NOT CAPTURED | appel non envoyé car il serait audité/persisté. La route existe dans le runtime. |

## J. Dashboard truth

Les appels dashboard lisent bien les API runtime, notamment `/statistics`, `/devices`, `/incidents`, `/missions`, `/timeline`, `/drone/status` et `/api/v1/datalake`; aucune valeur frontend statique n'a été considérée comme preuve.

Les réponses authentifiées de ces endpoints, ainsi que ML/security, avaient déjà été observées HTTP 200 pendant la validation précédente. Elles ne sont pas rappelées ici afin d'éviter un `http_request` dans `siem_events`.

Résultat : PASS — preuve précédente ; recapture live NOT CAPTURED par contrainte read-only.

## K. Database integrity

Les deux DB ont été ouvertes exclusivement avec `file:...?mode=ro`.

| DB | Taille (bytes) | SHA-256 | integrity_check | foreign_key_check | user_version | readings / alerts / SIEM / incidents / missions |
|---|---:|---|---|---:|---:|---|
| `data/digital_twin.db` | 43,835,392 | `aedc151dc721bcaaf8fdefeb066336e588fc0342bf4f6e221deab3ee2350812f` | ok | 0 | 0 | 29,201 / 47,909 / 112,555 / 79 / 36 |
| `digital_twin.db` | 15,409,152 | `a347df2000961d54484e00af43e29638cc4394058d6e6bcdf3ffd71c579d08db` | ok | 0 | 0 | 11,180 / 8,077 / 43,675 / 50 / 157 |

Résultat : PASS. Aucune migration ni DDL n'a été lancé.

## L. Docker/runtime

Les services backend, dashboard et Mosquitto sont `running`. Aucune image n'a été construite, aucun conteneur n'a été redémarré, et aucun volume n'a été modifié. Le runtime contient les modules Patch 3B effectivement auditables ; il n'y a donc pas de divergence source/image sur le pipeline MQTT/SIEM inspecté.

Résultat : PASS.

## M. Limitations

1. Le mandat `DATABASE_MODIFIED = 0` empêche de rejouer des requêtes API, WebSocket et MQTT : leur instrumentation peut écrire dans la DB active.
2. Les résultats API, JWT, CORS, WebSocket et drone signalés PASS sont des preuves de la validation déjà réalisée et confirmée dans le contexte, pas une nouvelle émission de trafic pendant ce snapshot.
3. Le lifecycle drone et le contenu live exact de `/drone/status` ne sont donc pas recapturés ; ils restent `NOT CAPTURED` dans cette étape.
4. `git diff --check` échoue (exit 2) sur des espaces de fin existants dans `backend/network/network_monitor.py` et `dashboard/src/index.css`. Aucun fichier n'a été modifié pour les corriger.
5. Le workspace est déjà dirty avec de nombreux changements et artefacts préexistants. Ce rapport est un nouvel artefact demandé ; aucun fichier source applicatif n'a été modifié.
6. Les tests automatisés et le build ne sont pas rejoués : ils peuvent créer des caches/artéfacts. Les preuves précédentes indiquent `286 passed, 2 warnings` et build dashboard réussi.

## N. Tableau PASS / FAIL / NOT CAPTURED

| Domaine | Résultat |
|---|---|
| Health / platform health | PASS — preuve précédente |
| JWT REST / rejet sans JWT / CORS | PASS — preuve précédente |
| JWT WebSocket | PASS — preuve précédente |
| MQTT sensor -> persistence | PASS — preuves DB runtime |
| Nouvelle publication MQTT | NOT CAPTURED |
| ML anomaly et séparation incident cyber | PASS — preuves DB runtime |
| network_flood / unknown_ip / unknown_device / ml_anomaly | PASS — preuves DB runtime |
| Alert correlation / SIEM evidence | PASS — PATCH3C confirmé |
| Incident dedup | PASS |
| Drone probe Paho 1.5.1 compatible | PASS — inspection |
| Drone lifecycle live / status endpoint live | NOT CAPTURED |
| Dashboard API truth | PASS — preuve précédente ; non recapturée |
| SQLite integrity / FK | PASS |
| Docker services / code runtime Patch 3B | PASS |
| Regression tests / dashboard build | PASS — preuves précédentes ; non rejoués |
| `git diff --check` | FAIL — espaces de fin préexistants, non corrigés |

## O. Verdict final

```text
FINAL_RUNTIME_VALIDATION_PARTIAL
```

Le runtime et les bases sont cohérents pour la migration : services actifs, Patch 3B réellement exécuté, chaîne MQTT/ML/security déjà démontrée, déduplication Alert/SIEM correctement interprétée, incidents dédupliqués, et intégrité SQLite valide. Le verdict reste `PARTIAL` et non `PASS` parce qu'une validation strictement DB=0 ne peut pas recapturer les scénarios actifs API/MQTT/drone sans les modifier, et parce que le lifecycle drone live n'a pas été observé dans ce snapshot.

```text
FINAL_RUNTIME_VALIDATION_COMPLETE
DATABASE_MODIFIED = 0
SCHEMA_MODIFIED = 0
SOURCE_MODIFIED = 0
MIGRATION_PERFORMED = 0
```
