# FINAL INTEGRATION VALIDATION — READ-ONLY + TESTS

Projet : `/home/abdo/Downloads/CyberPort`
Date de validation : 2026-09-19

## Verdict

```text
FINAL_VALIDATION_BLOCKED
```

La validation statique, les tests complets, le build et une partie du runtime sont passés. La validation intégrée ne peut toutefois pas être déclarée PASS car la stack Docker actuellement en cours d’exécution utilise des images anciennes qui ne contiennent pas les contrats PATCH3B/PATCH4B.

## 1. Environnement et préconditions

### Git

`git status --short` montre de nombreuses modifications et fichiers non suivis préexistants issus des PATCH précédents. Aucun fichier de code n’a été modifié pendant cette mission.

`git diff --check` échoue sur des espaces de fin préexistants dans :

- `backend/network/network_monitor.py`
- `dashboard/src/index.css`

Ces erreurs étaient présentes avant la validation et n’ont pas été corrigées afin de respecter le périmètre d’intégration sans patch correctif.

### Artefacts PATCH présents

Présents :

- `PATCH1_WEBSOCKET_DRONE_MISSION.md`
- `PATCH2_DASHBOARD_DATA_TRUTH.md`
- `PATCH3B_ML_SIEM_FIX.md`
- `PATCH4A_REALTIME_AUDIT.md`
- `PATCH4A_REALTIME_AUDIT.json`
- `PATCH4B_REALTIME_FIX.md`
- `dashboard/src/realtime.js`
- `dashboard/src/realtime.test.js`
- `data/digital_twin.db`
- `digital_twin.db`

### Migrations

Aucun processus `alembic`, script de migration ou migration manuelle n’a été lancé.

Cependant, l’analyse du démarrage montre deux opérations automatiques interdites par cette mission si le backend est redémarré :

- `backend/database/__init__.py` appelle `Base.metadata.create_all()` à l’import ;
- le même module appelle `_upgrade_legacy_schema()` avec `ALTER TABLE` et `CREATE INDEX` potentiels ;
- `backend/main.py` rappelle `DatabaseBase.metadata.create_all()` pendant le lifespan.

La stack était déjà active. Pour ne pas provoquer un redémarrage exécutant ces opérations de schéma, `docker compose up -d --build` n’a pas été exécuté.

Aucun volume n’a été supprimé. Aucun `down -v`, `system prune` ou nettoyage n’a été exécuté.

## 2. Tests Python complets

### Collecte

Commande :

```text
pytest --collect-only -q
```

Résultat :

```text
286 tests collected
```

Le nombre actuel est 286, et non 273 comme dans l’état historique.

### Exécution

Commande :

```text
pytest -q
```

Résultat :

```text
286 passed, 2 warnings in 2.96s
```

Statut :

```text
FULL_TEST_SUITE_PASS
```

Warnings non bloquants :

1. `StarletteDeprecationWarning` concernant l’intégration `httpx` de `TestClient`.
2. Avertissement SciPy/NumPy : SciPy installé demande NumPy `<1.25`, l’environnement contient NumPy `1.26.4`.

Aucun test n’a échoué. Aucun test n’a été supprimé ou modifié pour obtenir ce résultat.

## 3. Build dashboard

Commande :

```text
cd dashboard
npm run build
```

Résultat :

```text
Compiled successfully.
```

Bundle principal :

```text
154.14 kB gzip
```

Statut :

```text
BUILD_PASS
```

Le build concerne le code source actuel. Il ne prouve pas que le conteneur dashboard déjà démarré sert cette version.

## 4. Docker / Compose

### Configuration

Commande :

```text
docker compose config
```

Résultat : configuration résolue avec succès.

Avertissement : la clé `version` de `docker-compose.yml` est obsolète.

### Stack observée

La stack du projet est déjà active :

- backend : port `8000` ;
- dashboard : port `3000` ;
- mosquitto : port `1883`.

Les conteneurs ont été créés le 2026-09-09 et démarrés avant cette mission.

### Décision de non-redémarrage

Le backend Docker actuel exécute automatiquement `create_all` et `_upgrade_legacy_schema` au démarrage. Comme la mission interdit migration et modification de schéma, le redémarrage/rebuild du backend a été bloqué par sécurité.

Conséquence : la validation runtime porte sur la stack existante, pas sur une image fraîchement reconstruite à partir du code PATCH4B.

## 5. Health runtime

### `/health`

Réponse observée :

```json
{
  "status": "ok",
  "api": "ok",
  "database": "available",
  "mqtt": "connected"
}
```

Statut : `PASS`.

### `/api/v1/platform/health`

Réponse observée :

- service : `SecurIoT-Port` ;
- status : `operational` ;
- database : disponible ;
- MQTT : online ;
- WebSocket : disponible ;
- ROS2 : false, attendu pour ce projet ;
- drone simulator seen : false au moment de la première vérification.

Statut : `PASS` pour la disponibilité du service.

### Dashboard HTTP

```text
GET http://localhost:3000/ -> HTTP 200
```

Statut : `PASS` pour la disponibilité HTTP.

## 6. Authentication et WebSocket runtime

### REST

| TEST | RESULTAT |
|---|---|
| login admin valide | PASS, HTTP 200 |
| endpoint protégé sans JWT | PASS, HTTP 401 |
| endpoint protégé avec JWT | PASS, HTTP 200 |
| OPTIONS CORS | PASS, HTTP 200 |

### WebSocket

Le code source actuel (`backend/main.py`) contient bien la validation JWT avant `accept()`.

Les tests Python de `tests/test_main_mqtt.py` passent pour les cas token absent, invalide et valide.

Mais la stack Docker runtime révèle une divergence critique :

```text
backend container /app/backend/main.py:
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
```

Le conteneur actif accepte donc le WebSocket sans token.

Résultats runtime observés :

| TEST | RESULTAT |
|---|---|
| WebSocket sans JWT contre source actuelle | couvert par tests, PASS |
| WebSocket sans JWT contre conteneur actif | FAIL : connexion acceptée avec HTTP 101 |
| WebSocket avec JWT contre conteneur actif | PASS : HTTP 101 |

### Cause

Image Docker backend obsolète par rapport au code source PATCH1/PATCH4A/PATCH4B.

### Classification

```text
PREEXISTING_RUNTIME_IMAGE_MISMATCH
FINAL_VALIDATION_BLOCKED
```

Aucun code n’a été modifié pour masquer cette divergence.

## 7. MQTT end-to-end

Un scénario minimal normal a été publié via le broker local existant :

```text
port/gantry_crane/temperature
```

Payload : device `grue_G01`, type `temperature`, valeur `27.5`, token enregistré, timestamp Unix.

Résultat :

- message reçu par MQTT ;
- événement WebSocket reçu ;
- `event = telemetry` ;
- `type = temperature` ;
- `device_id = grue_G01` ;
- `last_value = 27.5` ;
- timestamp présent ;
- sensor reading observée dans la base runtime.

Statut : `PARTIALLY_VALIDATED`.

La chaîne MQTT et télémétrie fonctionne sur le conteneur actif, mais le conteneur n’est pas l’image actuelle PATCH4B.

## 8. Drone end-to-end

Un message minimal a été publié sur :

```text
drone/telemetry
```

Avec :

- `drone_01` ;
- position x/y/altitude ;
- batterie 87 ;
- status `flying` ;
- mission `integration-mission` ;
- timestamp ;
- token drone local.

### Résultat runtime observé

Le conteneur actif a envoyé :

```json
{
  "event": "drone_telemetry",
  "type": "drone",
  "mission_id": "integration-mission",
  "status": "flying",
  "battery": 87.0,
  "timestamp": "present"
}
```

Mais :

- `type` est `drone`, pas `drone_telemetry` ;
- `drone_id` est absent dans l’événement reçu ;
- `position` est absente.

Cela contredit le contrat PATCH4A/PATCH4B.

### `/drone/status`

L’endpoint runtime répond avec les champs :

- `drone_id` ;
- `x`, `y`, `altitude` ;
- `battery` ;
- `status` ;
- `mission_id` ;
- `updated_at`.

La réponse reflétait le message drone envoyé, mais le WebSocket runtime n’exposait pas le contrat canonique attendu.

### États LIVE/STALE/DISCONNECTED/UNKNOWN

- Helpers et tests actuels : validés par les tests frontend PATCH4B.
- Dashboard source actuel : build réussi.
- Dashboard conteneur actif : image ancienne, sans les marqueurs PATCH4B (`wsStatus`, handlers lifecycle, reconnexion) observés dans `/app/src/App.jsx`.

Statut : `FAIL` pour la validation end-to-end Docker de la version PATCH4B.

## 9. ML / alert / SIEM

Le mécanisme existant `/simulate/spoof` a été utilisé une seule fois, sans flood massif.

Résultat HTTP :

```text
POST /simulate/spoof -> HTTP 200
```

La base runtime `data/digital_twin.db` montre :

- des alertes `bad_token` ;
- des alertes `unknown_ip` ;
- des alertes `ml_anomaly` ;
- des SIEM events associés ;
- des incidents associés.

Cependant, les lignes récentes observées dans le runtime montrent plusieurs alertes pour certains événements logiques, notamment des occurrences `bad_token` et `ml_anomaly` rapprochées.

Cela correspond au comportement de l’image backend ancienne, avant la source canonique PATCH3B. Le test source PATCH3B `test_same_logical_siem_event_creates_one_primary_alert` passe dans la suite Python, mais cette propriété n’est pas démontrée par le conteneur runtime obsolète.

Statut :

```text
SOURCE_TESTS_PASS
RUNTIME_IMAGE_BLOCKED
```

La séparation sémantique `ml_anomaly` / cyber attack est validée par les tests source PATCH3B, mais ne peut pas être déclarée intégrée dans l’image active ancienne.

## 10. Security event

Le scénario `/simulate/spoof` a produit dans l’environnement local :

```text
événement MQTT
 -> bad_token / unknown_ip / ml_anomaly selon les branches
 -> alertes
 -> SIEM events
 -> incidents observés
```

Aucun système externe n’a été attaqué.

Le runtime a toutefois produit des alertes dupliquées dans l’image ancienne. La règle PATCH3B ne peut donc pas être validée comme déployée tant que l’image backend n’est pas reconstruite avec une procédure de démarrage compatible avec l’interdiction de migration.

## 11. Dashboard et valeurs fictives

Endpoints vérifiés avec JWT :

- `/statistics` : HTTP 200 ;
- `/devices` : HTTP 200, 7 équipements observés ;
- `/incidents` : HTTP 200 ;
- `/missions` : HTTP 200 ;
- `/drone/status` : HTTP 200 ;
- `/api/v1/datalake` : HTTP 200.

Le nombre runtime observé est 7, pas 8.

Aucun compteur forcé `42 threats` n’a été observé dans les réponses API.

La valeur batterie `87.0` provenait du message drone publié, pas d’un fallback `100`.

Une santé à 100 peut apparaître pour un device sans anomalie historique ; elle provient de la formule backend `/health/{device_id}`, pas d’un fallback dashboard ajouté pendant cette mission.

La validation visuelle du dashboard PATCH4B n’est pas complète car le conteneur dashboard existant est ancien et son `/app/src/App.jsx` ne contient pas le nouveau lifecycle WebSocket.

## 12. Database safety

### Hashes à l’entrée de mission

```text
8d7858a5590ea56ebd432cecbb38ac43f73571f50a94a3e0cf2a69a92efa9cb6  data/digital_twin.db
d660f1b5bc6eff393426ca2d9dab255e6004770872d9c9647963cac7b85a7cc1  digital_twin.db
```

### Snapshot final observé

```text
9d667e0b887988be8c7f2882f3b5595bc8a1720573381ed3fb58d98484ed1d62  data/digital_twin.db
711e40b6b4cc2e0d74e2094650523455a90f634011752023395dee5334c0271e  digital_twin.db
```

### Intégrité finale

```text
data/digital_twin.db: integrity_check = ok
 digital_twin.db:     integrity_check = ok
```

### Comptages

#### `data/digital_twin.db`

| TABLE | ENTRÉE | SNAPSHOT FINAL | DELTA OBSERVÉ |
|---|---:|---:|---:|
| `sensor_readings` | 29069 | 29072 | +3 |
| `alerts` | 47679 | 47694 | +15 |
| `siem_events` | 111550 | 111581 | +31 |
| `incidents` | 74 | 76 | +2 |
| `missions` | 35 | 35 | 0 |

Les deltas correspondent aux scénarios MQTT normal, drone, spoof et aux événements d’audit HTTP générés par les requêtes runtime. Les services sont restés actifs et le polling dashboard/audit HTTP peut continuer à ajouter des événements après ce snapshot.

#### `digital_twin.db`

Le runtime Docker utilise `/app/data/digital_twin.db`, donc `digital_twin.db` n’est pas la base active de la stack Compose.

| TABLE | SNAPSHOT APRÈS TESTS | SNAPSHOT FINAL |
|---|---:|---:|
| `sensor_readings` | 11180 | 11180 |
| `alerts` | 8077 | 8077 |
| `siem_events` | 43651 | 43651 |
| `incidents` | 50 | 50 |
| `missions` | 157 | 157 |

La différence de hash de `digital_twin.db` par rapport au hash PATCH4A historique est liée à des événements SIEM d’audit observés pendant l’activité de tests/runtime ; aucune table métier n’a augmenté dans le snapshot final après cette phase.

Aucune modification de schéma n’a été observée : `PRAGMA user_version = 0` et `integrity_check = ok` sur les deux bases.

## 13. Problèmes et risques restants

### BLOQUANT

1. **Images Docker obsolètes** : le backend runtime accepte `/ws` sans JWT et émet le contrat drone ancien `type: drone`.
2. **Dashboard runtime obsolète** : le conteneur actif ne contient pas le lifecycle/reconnect PATCH4B.
3. **Redémarrer/rebuilder le backend exécuterait des opérations automatiques de schéma** (`create_all`, `_upgrade_legacy_schema`), interdites pendant cette mission.
4. **Le runtime actif reproduit des doublons d’alertes historiques** alors que les tests source PATCH3B passent.

### IMPORTANT MAIS NON BLOQUANT POUR LE CODE SOURCE

5. `git diff --check` reste en échec sur des espaces de fin préexistants.
6. La clé `version` de Compose est obsolète.
7. Le polling et l’audit HTTP peuvent continuer à modifier naturellement la base runtime active.
8. Les deux fichiers SQLite restent deux historiques/runtime roots différents.

## 14. Décision migration SQLite

```text
MIGRATION_NOT_AUTHORIZED_BY_VALIDATION
```

Aucune migration SQLite ne doit démarrer maintenant.

Avant toute migration, il faut :

1. préparer une procédure de démarrage qui n’exécute pas implicitement `create_all`/`_upgrade_legacy_schema` ;
2. reconstruire les images Docker avec le code PATCH3B/PATCH4B ;
3. redéployer sur une copie de validation, pas sur les bases historiques ;
4. revalider JWT WebSocket, contrat `drone_telemetry`, déduplication et état drone ;
5. comparer les bases et les événements sur cette copie ;
6. obtenir une nouvelle validation intégrée PASS.

## Tableau final

| COMPONENT | TEST | RESULT | EVIDENCE | ISSUE |
|---|---|---|---|---|
| Git | status / diff check | PARTIAL | status capturé ; diff check espaces de fin | préexistant |
| PATCH artifacts | présence fichiers | PASS | fichiers PATCH1-4 présents | aucune |
| migrations | processus/script actif | PASS | aucun processus migration ; aucun script lancé | démarrage Docker contient opérations automatiques de schéma |
| SQLite | existence/intégrité | PASS | deux fichiers présents ; `integrity_check=ok` | hashes changent selon runtime autorisé |
| pytest collection | `pytest --collect-only -q` | PASS | 286 tests collectés | historique annoncé 273 obsolète |
| pytest full | `pytest -q` | PASS | 286 passed, 2 warnings | warnings environnement |
| dashboard build | `npm run build` | PASS | Compiled successfully | conteneur non reconstruit |
| Compose config | `docker compose config` | PASS | configuration résolue | warning `version` obsolète |
| Docker services | stack existante | PARTIAL | backend/dashboard/mosquitto Up | images créées avant PATCH4B |
| `/health` | status/database/mqtt | PASS | ok / available / connected | image runtime ancienne |
| REST auth | sans/avec JWT | PASS | 401 puis 200 | aucune |
| CORS | OPTIONS | PASS | HTTP 200 | aucune |
| WS sans JWT | refus attendu | FAIL runtime | conteneur renvoie 101 | image backend ancienne sans auth WS |
| WS avec JWT | connexion | PASS runtime | HTTP 101 | contrat applicatif reste ancien |
| MQTT sensor | telemetry -> WS/reading | PARTIAL | event telemetry et `grue_G01` reçus | stack ancienne |
| MQTT drone | contract `drone_telemetry` | FAIL runtime | `type=drone`, position absente | image backend ancienne |
| drone freshness | UNKNOWN/STALE/DISCONNECTED | PASS source tests / PARTIAL runtime | tests frontend PATCH4B | dashboard conteneur ancien |
| ML/SIEM | anomaly -> alert/SIEM | PASS source / BLOCKED runtime | tests PATCH3B ; événements runtime présents | dédup runtime ancien non garanti |
| alert duplication | une alerte primaire | PASS source / FAIL runtime | tests source pass ; lignes runtime dupliquées | image backend ancienne |
| dashboard values | endpoints / fake values | PARTIAL | 7 devices, API 200 | validation visuelle PATCH4B impossible sur image ancienne |
| migration readiness | décision | BLOCKED | runtime integration non homogène | ne pas migrer |

## Conclusion

Les tests source et le build actuel sont verts :

```text
286 passed
BUILD_PASS
```

La validation runtime intégrée est bloquée par une divergence de déploiement : les conteneurs actifs datent d’avant PATCH3B/PATCH4B et ne contiennent pas les contrats corrigés.

Le verdict est donc :

```text
FINAL_VALIDATION_BLOCKED
```
