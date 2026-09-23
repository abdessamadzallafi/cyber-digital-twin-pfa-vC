# FINAL_STABILIZATION_AUDIT

## 0. Périmètre et méthode

Audit technique en lecture seule du dépôt `/home/abdo/Downloads/CyberPort`, réalisé avant toute modification fonctionnelle.

- Aucun fichier existant n’a été modifié, supprimé ou migré.
- Le seul fichier créé par cette mission est ce rapport.
- Les tests n’ont pas été exécutés afin d’éviter les effets de bord; la collecte seule a été exécutée avec `pytest --collect-only -q -p no:cacheprovider`.
- Résultat de collecte: **273 tests collectés**, avertissement Starlette/httpx observé.
- `docker compose config --quiet`: succès, avec avertissement sur la clé Compose `version` obsolète.
- Stack existante observée: `mosquitto`, `backend`, `dashboard` actifs sur 1883, 8000 et 3000.
- État Git initial: 11 fichiers modifiés, 1 fichier supprimé, 1 fichier non suivi. Ces changements préexistants ne sont pas attribués à l’audit.

## 1. Arborescence réelle

### Noyau applicatif

- `backend/`: FastAPI historique et adaptateurs: `main.py`, `auth.py`, `mqtt_listener.py`, `decision_engine.py`, `mission_planner.py`, `report_generator.py`, `network/`, `ml/`, `security/`, `siem/`, `ros/`, `mqtt/`, `udp/`, `database/`, `datalake/`, `services/`, `api/`, `schemas/`.
- `smart_port/`: architecture canonique annoncée: `edge/`, `communication/`, `data/`, `analytics/`, `mission/`, `application/`.
- `dashboard/`: React source dans `dashboard/src`, build déjà présent dans `dashboard/build`.
- `simulation/`: capteurs, drone MQTT, seed Data Lake, attaquant, GPS, caméra, robot, lancement Gazebo.
- `attacks/`: quatre scripts MQTT d’attaque.
- `gazebo/`: monde SDF, monde portuaire et launch ROS/Gazebo.
- `tests/`: 10 fichiers de tests.

### Artefacts et données présents

- Bases: `digital_twin.db`, `data/digital_twin.db`.
- Data Lake: `data/data_lake/{missions,security,telemetry}` et `data_lake/{logs,missions,network,security,telemetry}`.
- Rapports PDF dans `reports/`.
- Logs dans `logs/backend.log`.
- Modèles joblib/pickle dans `backend/ml/models/`.
- Certificats et configuration TLS dans `certs/`, `mosquitto-tls.conf`.
- Archives/legacy: `validate_vc.py.backup`, `validate_vc.py.backup2`, mondes Gazebo `.backup2` et `.before_plugin_fix`, `dashboard/build`.

## 2. Services Docker

`docker-compose.yml` définit:

1. `mosquitto`: `eclipse-mosquitto:2`, port 1883, montage `mosquitto.conf`.
2. `backend`: build `backend/Dockerfile`, port 8000, dépend de Mosquitto, volume `./data:/app/data` et `./reports:/app/reports`, `.env`, SQLite `/app/data/digital_twin.db`.
3. `dashboard`: build `./dashboard`, port 3000, dépend du backend, API navigateur `http://localhost:8000`, WebSocket `ws://localhost:8000/ws`.

Absences importantes: pas de healthcheck Compose, `depends_on` n’attend pas la disponibilité du broker/API, aucune limitation de ressources, pas de réseau explicite, pas de persistance dédiée Mosquitto, et la clé `version` est obsolète.

## 3. Entrées/sorties des composants

| Composant | Entrées | Sorties/effets |
|---|---|---|
| MQTT listener | `port/#`, `drone/#`, JSON | SQLite, JSONL, alertes, SIEM, WebSocket |
| UDP gateway | datagrammes UDP port 9000 | normalisation, SQLite/JSONL/SIEM via service HTTP interne |
| HTTP API | REST JSON/form-data | réponses REST, SQLite, JSONL, MQTT commandes |
| SIEM | `SiemEventIn` HTTP/MQTT/audit | `siem_events`, `alerts`, `incidents`, JSONL security |
| ML | télémétrie et métriques réseau | prédictions, alertes `ml_anomaly`, recommandation mission |
| Drone manager | commandes REST et télémétrie MQTT | missions SQLite, MQTT `drone/mission`, état, JSONL missions |
| Dashboard | REST + `/ws` | visualisation, commandes simulations/mission |
| Data Lake | événements mapping | fichiers JSONL append-only |
| Rapports | SQLite/SIEM + fenêtre temporelle | PDF dans `reports/` |

## 4. Routes FastAPI réellement disponibles

### Routes racine de `backend/main.py`

- `GET /health`, `GET /health/{device_id}`
- `POST /token`
- `GET /statistics`, `/dashboard`, `/risk`, `/network/flow/{device_id}`, `/network/stats`
- `POST /simulate/flood`, `/simulate/spoof`, `/simulate/unknown`, `/simulate/impossible`
- `POST /force_mission/{device_id}`
- `GET /drone/status`, `/missions`, `/drone/missions`
- `POST /report/{device_id}`
- `GET /equipments`, `/datalake`, `/reports`, `/measures/{device_id}`, `/alerts`, `/ml/anomalies`, `/security/events`
- `POST /incidents`, `GET /incidents`, `PUT /incidents/{incident_id}/resolve`
- `GET /timeline`, `/devices`
- WebSocket `/ws`

### Routes versionnées

- `/api/v1`: `GET /devices`, `POST /telemetry`, `GET /devices/{device_id}/telemetry`, `GET /datalake`.
- `/api/v1/ops`: `/map`, `/datalake`, `/network`, `/security`, `/mission`, `/analytics`, `/statistics`, `/reports`, `/siem/timeline`.
- `/api/v1/siem`: `POST/GET /events`, `GET /risk`, `GET /incidents`, `POST /incidents/{id}/resolve`, `GET/POST /reports`.
- `/api/v1/ai`: `POST /predict`.
- `/api/v1/drone`: `GET /status`, `POST /missions`, `/missions/start`, `/missions/return-home`, `/telemetry`, `/camera/start`, `/tick`.
- `/api/v1/platform`: `/health` et `/api/v1/edge/devices` dans `smart_port/application/router.py`.

Les routes racine et versionnées exposent deux façades concurrentes. Certaines réponses sont des ORM SQLAlchemy directs et d’autres des contrats Pydantic/dicts.

## 5. Modèles de données

### Modèle historique `backend/database.py`

`SensorReading`, `Alert`, `NetworkFlow`, `Mission`, `Incident`. Il ne contient pas `SiemEvent`, `Device`, `Drone`, `Report`, `LogEntry`, ni les champs de déduplication enrichis.

### Modèle canonique `backend/database/models.py`

Les mêmes tables plus `SiemEvent`, `Device`, `Drone`, `Report`, `LogEntry`. `Mission.drone_id` mappe la colonne physique legacy `robot_id`; `Incident.drone_mission_id` mappe `robot_mission_id`; `Incident` contient `first_seen`, `last_seen`, `occurrence_count`, `dedup_key`.

### Contrats HTTP

`backend/schemas/platform.py`, `backend/schemas/siem.py`, `backend/schemas/ai.py`. `TelemetryIn` accepte bool/string pour `status`, GPS, port source, token, topic et `extra`.

## 6. Sources de vérité équipements

Source déclarée canonique: `smart_port/edge/device_registry.py`, avec 9 profils (`grue_G01`, `station_H01`, `portique_P01`, `camera_Q01`, `camion_C12`, `portail_N01`, `entrepot_E01`, `parking_P01`, `drone_01`) et 8 alias legacy (`temp_01`, `hum_01`, `vib_01`, `cam_01`, `gps_01`, `gate_01`, `smoke_01`, `pres_01`).

Mais plusieurs vues ne lisent pas ce registre: `/devices` racine dérive les équipements de `sensor_readings`; `/equipments` fait de même; `/api/v1/devices` lit le registre; le dashboard mélange registre, lectures et constantes locales. La base `devices` est définie mais contient 0 ligne dans les deux bases observées.

## 7. Pipeline MQTT

1. Paho se connecte au broker configuré.
2. Souscriptions `port/#` et `drone/#` dans `backend/mqtt_listener.py:on_connect`.
3. Callback `on_message` décode JSON et pousse dans une queue asyncio bornée.
4. `mqtt_worker` appelle `process_message`.
5. `DeviceGateway.normalize` puis `EventNormalizer.normalize`.
6. `write_event("telemetry", ...)` écrit le Data Lake.
7. Les types drone vont vers `_process_drone_telemetry`; les autres vont vers `SensorReading`, `process_network_data`, `make_decision`.
8. Les alertes sont persistées, certaines envoyées à `SmartPortSiem.collect`, puis un événement dashboard est publié.

Points sensibles: messages rejetés quand la queue est pleine, absence de persistance MQTT, pas de limite de taille JSON/payload, et le broker Compose est configuré sans authentification ni TLS par défaut.

## 8. Pipeline ML

Deux piles coexistent:

- Legacy: `backend/ml/anomaly_detector.py`, modèles `temperature_model.pkl`, `humidity_model.pkl`, `vibration_model.pkl`, `smoke_model.pkl`, `camera_model.pkl`.
- Avancée: `backend/ml/prediction_service.py`, modèles `advanced_*.pkl`, domaines température, humidité, batterie, trajectoire drone, défaillance capteur, flood, spoofing, unknown device, trafic réseau.

`decision_engine.make_decision` exécute les deux familles plus le modèle réseau legacy, puis corrèle les alertes. Les sorties anormales entraînent parfois une recommandation d’action drone.

## 9. Pipeline cybersécurité

`backend/security/engine.py:check_security` valide identité/token/topic via le registre puis compte les messages par device sur une fenêtre de 5 s. `backend/network/network_monitor.py` calcule une fenêtre réseau de 10 s, détecte >20 paquets et compare l’IP au registre. `decision_engine.py` ajoute les signaux ML et corrélation.

## 10. Pipeline SIEM

Deux chemins:

- `PlatformService.ingest_telemetry`: `SiemService.evaluate` puis `SmartPortSiem.collect` pour l’audit d’ingestion.
- `mqtt_listener.process_message`: alertes directes puis `SmartPortSiem.collect(..., manage_incident=False)` par alerte.
- `audit_http_requests`: un événement SIEM pour chaque requête HTTP, y compris les endpoints de consultation.

`SmartPortSiem.collect` crée `SiemEvent`, corrèle, crée éventuellement une alerte/incident, écrit le Data Lake et calcule le risque.

## 11. Pipeline incidents

Création possible dans:

1. `backend/services/action_dispatcher.py:create_or_update_incident` pour détection ML/réseau/action.
2. `backend/siem/managers.py:IncidentManager.create_or_update` pour les événements SIEM high/critical.
3. `backend/main.py:create_incident` via `POST /incidents`, sans déduplication.

Les deux gestionnaires de déduplication n’utilisent pas la même clé ni exactement la même logique. Les incidents manuels peuvent donc dupliquer ceux créés automatiquement.

## 12. Pipeline missions drone

Création possible dans:

1. `backend/main.py:force_mission` -> `backend/mission_planner.py:create_mission` -> `DroneManager.create_inspection`.
2. `backend/api/drone.py:create_drone_mission`.
3. `backend/services/action_dispatcher.py:handle_detection`.
4. `DroneManager.create_inspection` lui-même.

La mission est insérée en SQLite, publiée sur `drone/mission`, éventuellement envoyée à la frontière ROS2, inscrite dans JSONL `missions`, et l’état mémoire du manager est mis à jour. `simulation/drone_sim.py` valide token/drone/waypoints, lance un worker unique et publie télémétrie, GPS, caméra et événements.

Le drone est bien une simulation MQTT externe. Il n’exécute pas un drone réel et n’est pas une dépendance physique du port.

## 13. Pipeline dashboard

`dashboard/src/App.jsx` utilise REST toutes les 5 s et WebSocket `/ws`. Il appelle les routes racine `/statistics`, `/risk`, `/devices`, `/incidents`, `/missions`, `/timeline`, `/drone/status`, `/api/v1/datalake`, puis `/health/{device_id}`, `/measures/{id}`, `/report/{id}`. Les commandes appellent `/simulate/*` et `/force_mission/*`.

Le dashboard ne consomme pas les routes versionnées ops/SIEM pour ses vues principales. Le WebSocket est techniquement disponible mais accepté sans authentification et les messages ne sont pas validés côté client.

## 14. Bases SQLite utilisées

Inspection en lecture seule:

- `digital_twin.db`: tables opérationnelles, 8 077 alerts, 11 180 sensor_readings, 50 incidents, 157 missions, 43 639 siem_events; `devices`, `drones`, `network_flows`, `reports`, `logs` à 0 ligne.
- `data/digital_twin.db`: 47 675 alerts, 29 069 sensor_readings, 74 incidents, 35 missions, 111 545 siem_events; mêmes tables auxiliaires à 0 ligne.

Le défaut local est `sqlite:///./digital_twin.db`; Docker utilise `/app/data/digital_twin.db`. Le contenu historique est donc divisé selon le mode de lancement.

## 15. JSONL et logs

Flux déclarés par `smart_port/data/data_lake.py`: `telemetry`, `security`, `missions`, `network`, `logs`. Alias: `siem -> security`, `audit -> logs`, `mission -> missions`.

Répertoires réellement présents:

- `data/data_lake/telemetry`, `security`, `missions`.
- `data_lake/telemetry`, `security`, `missions`, `network`, `logs`.

`logs/backend.log` est un log applicatif historique. Les répertoires et bases sont ignorés par Git mais présents localement. Les fichiers JSONL ne sont pas une source unique entre local et Docker.

## 16. Scripts de simulation

- Capteurs: `simulation/capteur_temperature.py`, `capteur_humidite.py`, `capteur_vibration.py`, `detecteur_fumee.py`, `detecteur_presence.py`, `barriere_sim.py`, `camera_sim.py`, `gps_conteneur.py`.
- Drone: `simulation/drone_sim.py`.
- Attaquant: `simulation/attacker_sim.py`.
- Data Lake: `simulation/data_lake_seed.py`.
- Réseau: `simulation/network_config.py`.
- Robot legacy: `simulation/robot_sim.py`.
- ROS/Gazebo: `simulation/launch/port_simulation.launch.py`, `gazebo/launch/terminal.launch.py`.
- Probe ajouté avant l’audit mais non par cet audit: `scripts/drone_pipeline_probe.py`.

## 17. Scénarios d’attaque

- `attacks/flood_attack.py`: rafale MQTT.
- `attacks/spoofing_attack.py`: token/identité usurpée.
- `attacks/unknown_device_attack.py`: device inconnu.
- `attacks/impossible_value_attack.py`: valeur capteur impossible.
- Routes protégées `/simulate/flood`, `/simulate/spoof`, `/simulate/unknown`, `/simulate/impossible` dans `backend/main.py`.

Les routes de simulation MQTT utilisent un client nommé fixe `attack-simulator`; les scripts directs utilisent généralement localhost et client Paho legacy. Ils ne sont pas tous alignés sur la configuration TLS/QoS du listener.

## 18. Tests

Fichiers présents: `conftest.py`, `test_action_dispatcher.py`, `test_drone_simulator.py`, `test_event_normalizer.py`, `test_final_stabilisation_predict_reports.py`, `test_http_common_event.py`, `test_main_mqtt.py`, `test_mqtt_listener_event.py`, `test_mqtt_safety.py`, `test_siem_report_regression.py`, `test_stabilisation_e8.py`, `test_udp_common_event.py`.

273 tests ont été collectés sans exécution. La couverture est forte sur normalisation, MQTT simulé, dispatcher, drone et contrats; elle ne prouve pas le déploiement Docker, la sécurité réelle du broker, les migrations SQLite, le WebSocket authentifié, ni la cohérence des deux bases.

## 19. Modules anciens/legacy

- `backend/main.py`, `backend/database.py`, `backend/models.py`, `backend/schemas.py`, `backend/decision_engine.py`, `backend/mission_planner.py` restent des façades/chemins historiques.
- `backend/database/`, `backend/services/`, `backend/siem/`, `backend/events/` représentent la couche canonique plus récente.
- `smart_port/` est l’architecture cible, mais n’a pas remplacé tous les appels racine.
- `simulation/robot_sim.py`, `smart_port/mission/ros2_bridge.py`, `backend/ros/`, `gazebo/`, `start_all.bat` appartiennent au périmètre legacy/expérimental.
- `validate_vc.py.backup*`, `architecture.txt`, fichiers d’inventaire et build frontend sont des artefacts historiques ou générés.

## 20. Références Digital Twin / ROS2 / Gazebo / ancien drone

Références actives ou historiques relevées:

- `digital_twin.db`, Compose et documentation.
- Nom package frontend `cyber-digital-twin-dashboard`.
- `backend/ros/*`, `smart_port/mission/ros2_bridge.py`.
- `gazebo/*`, `simulation/launch/port_simulation.launch.py`.
- `simulation/robot_sim.py`, TurtleBot3 dans le launch ROS.
- chemins codés en dur vers `~/Downloads/cyber-digital-twin-pfa-vC` dans les launch scripts et backups.
- `backend/ros/drone_manager.py` importe encore toutes les abstractions ROS, même si `ROS2Interface` est optionnelle.

Cela contredit partiellement le cadrage officiel: ROS2/Gazebo ne sont pas le cœur final, mais ils restent visibles dans le chemin de création mission et dans le démarrage expérimental.

## 21. Tous les endroits de création d’alertes

- `backend/mqtt_listener.py`: alertes directes drone et alertes de `decision_engine`.
- `backend/services/platform_service.py`: alertes issues de `SiemService.evaluate`.
- `backend/siem/managers.py:AlertManager.create`: alertes SIEM high/critical.
- `backend/main.py` endpoints de simulation et audit HTTP indirectement via SIEM.
- `backend/security/engine.py`, `backend/network/network_monitor.py`, `backend/decision_engine.py`: producteurs de tuples d’alertes.

## 22. Tous les endroits de création d’incidents

- `backend/services/action_dispatcher.py`.
- `backend/siem/managers.py`.
- `backend/main.py:create_incident`.
- `SmartPortSiem.collect` déclenche `IncidentManager` selon la sévérité.

## 23. Tous les endroits de création de missions

- `backend/main.py:force_mission`.
- `backend/mission_planner.py:create_mission`.
- `backend/api/drone.py:create_drone_mission`.
- `backend/services/action_dispatcher.py:handle_detection`.
- `backend/ros/drone_manager.py:create_inspection`.
- Scripts `simulation/drone_sim.py` et `scripts/drone_pipeline_probe.py` publient/consomment des missions mais ne remplacent pas le manager backend.

## 24. Calculs statistiques et risque

- `/statistics`: devices distincts depuis `sensor_readings`, activité <10 s, alertes totales, attaques par liste statique, anomalies ML.
- `/dashboard`, `/devices`: même seuil d’activité de 10 s et zones inférées par substring du device ID.
- `/health/{device_id}`: `100 - int(anomalies/total * 200)`, sans fenêtre temporelle.
- `/risk`: ratio attaques/alertes sur 5 minutes, score borné 0–100.
- `RiskScoreService`: somme des points de sévérité sur 60 minutes, bornée à 100.
- `/api/v1/ops/analytics`: `anomalies / telemetry_events` sans fenêtre et avec liste partielle de types.
- `CorrelationEngine`: répétition auth, mélange network/sensor, fréquence >=5 sur 5 minutes.
- `network_monitor`: paquets, bytes, intervalle moyen, throughput sur 10 secondes.

Ces calculs ne mesurent pas la même fenêtre ni les mêmes tables/types; les deux scores nommés `risk` ne sont donc pas comparables.

## 25. Incohérences frontend/backend

1. Le dashboard affiche le risque avec `risk.risk_score`; le SIEM versionné expose `RiskScoreOut.score`. La route racine `/risk` fournit les deux, mais la vue versionnée ne garantit pas `risk_score`.
2. `/api/v1/datalake` est bien appelé, mais la route est protégée par dépendance alors que `/api/v1/telemetry` est listée public dans le middleware; la politique est incohérente.
3. Le dashboard construit une liste de 8 équipements alors que le registre contient 9 profils, dont le drone.
4. Les statuts WebSocket attendus par le dashboard (`update.type === 'drone'`) ne correspondent pas systématiquement aux événements backend (`event: "drone_telemetry"`).
5. Le dashboard utilise `/force_mission/entrepot_E01` et `/missions` plutôt que l’API drone versionnée.
6. Le dashboard ne propose pas la simulation `unknown`, bien que la route existe.
7. Le dashboard ne présente pas d’action de résolution d’incident malgré les routes disponibles.
8. `last_value` et `value/status/people_count` sont mélangés; `value || status` perd les valeurs falsy comme 0.
9. Les données carte sont des constantes visuelles, non les coordonnées backend.
10. Le build déjà présent peut être différent de `src`, et `dashboard/public/port.jpeg` est ignoré par Git alors qu’il est requis visuellement.

## 26. Problèmes de sécurité

### SEC-01 — CRITICAL

- Fichier/fonction: `backend/core/config.py:Settings`, `backend/auth.py:create_access_token/get_current_user`.
- Problème: `SMART_PORT_JWT_SECRET` vaut chaîne vide par défaut hors production.
- Conséquence: en démarrage local sans `.env`, la clé de signature est prévisible/vide; un tiers peut fabriquer des JWT valides.
- Correction proposée: refuser toute clé vide dès qu’un endpoint protégé est utilisé; fournir uniquement un secret local explicitement généré hors dépôt.
- Risque de correction: perte de compatibilité de démarrage local/documentation.
- Tests: JWT forgé avec secret vide, démarrage sans secret, démarrage avec secret valide.

### SEC-02 — HIGH

- Fichier/fonction: `backend/auth.py` module initialization.
- Problème: mots de passe par défaut `admin`/`operateur` si variables absentes.
- Conséquence: compromission immédiate d’une installation mal configurée.
- Correction: supprimer les identifiants de fallback et échouer en environnement non contrôlé; documenter un bootstrap sûr.
- Risque: démo locale non démarrable sans configuration.
- Tests: absence de secrets, mauvais mot de passe, login valide après configuration.

### SEC-03 — HIGH

- Fichier/fonction: `backend/main.py:websocket_endpoint`, `backend/auth.py:PUBLIC_ENDPOINTS`.
- Problème: `/ws` est public et aucune authentification/token n’est contrôlée sur le handshake.
- Conséquence: fuite des télémétries, alertes, missions et événements à tout client réseau.
- Correction: authentifier le handshake et filtrer les événements par rôle.
- Risque: compatibilité avec le dashboard et clients WebSocket existants.
- Tests: handshake sans token refusé, token valide accepté, isolation de messages.

### SEC-04 — HIGH

- Fichier: `mosquitto.conf`, `docker-compose.yml`, `backend/mqtt_listener.py`.
- Problème: MQTT exposé sur 1883 sans auth/TLS dans Compose; les certificats existent mais ne sont pas activés par défaut.
- Conséquence: injection, écoute et usurpation de messages.
- Correction: listener TLS/auth obligatoire en déploiement; limiter l’exposition au réseau interne.
- Risque: incompatibilité avec scripts/simulateurs localhost.
- Tests: connexion anonyme refusée, certificat valide accepté, certificat invalide refusé.

### SEC-05 — HIGH

- Fichier/fonction: `backend/main.py:simulate_flood`, `publish_attack`.
- Problème: simulation flood synchrone dans le thread de requête et publication répétée sans rate limit applicatif.
- Conséquence: blocage worker HTTP, auto-déni de service et amplification.
- Correction: file de simulation bornée, rôle admin, rate limit et timeout strict.
- Risque: scénario de démo plus lent/non déterministe.
- Tests: concurrence HTTP, limite de fréquence, broker indisponible.

### SEC-06 — MEDIUM

- Fichier/fonction: `backend/main.py:reports`, `list_reports_root`, génération PDF.
- Problème: chemins relatifs `reports/` dépendants du répertoire courant.
- Conséquence: rapport invisible ou écrit hors volume selon le mode de démarrage.
- Correction: chemin absolu configuré et partagé.
- Risque: déplacement de rapports existants.
- Tests: démarrage depuis autre cwd, lecture/écriture Docker.

## 27. Problèmes de données

### DATA-01 — CRITICAL

- Fichiers: `smart_port/config.py`, `docker-compose.yml`, `backend/database.py`, `backend/database/`.
- Problème: deux bases SQLite réelles et deux définitions ORM concurrentes.
- Conséquence: données divisées, schéma dépendant de l’import et résultats dashboard non reproductibles.
- Correction: choisir un unique module ORM et une unique URL configurée; conserver une façade de compatibilité temporaire.
- Risque: incompatibilité avec la base historique `robot_id/robot_mission_id`.
- Tests: même URL dans local/Docker, inspection schéma, lecture d’anciens enregistrements.

### DATA-02 — HIGH

- Fichier: `backend/database/__init__.py:_upgrade_legacy_schema`.
- Problème: `create_all` et `ALTER TABLE` sont exécutés automatiquement à l’import.
- Conséquence: démarrage avec effet de bord de type migration, sans versionnement ni transaction de migration explicite.
- Correction: migration versionnée et étape de déploiement contrôlée; ne pas supprimer de données.
- Risque: verrou SQLite et incompatibilité avec bases anciennes.
- Tests: base vide, base ancienne, concurrence de deux workers.

### DATA-03 — HIGH

- Fichiers: `smart_port/data/data_lake.py`, `backend/services/platform_service.py`, `backend/mqtt_listener.py`.
- Problème: les pipelines écrivent plusieurs fois le même événement dans telemetry/security/SIEM et deux racines de Data Lake.
- Conséquence: statistiques de volume et corrélation biaisées, doublons d’audit.
- Correction: identifiant d’événement commun et politique claire raw/canonical/audit.
- Risque: perte apparente de volume lors de la déduplication.
- Tests: un événement HTTP/MQTT -> cardinalité attendue de chaque flux.

### DATA-04 — MEDIUM

- Fichier: `backend/main.py:create_incident`.
- Problème: création manuelle sans `dedup_key`, `first_seen`, `last_seen`, `occurrence_count` explicites.
- Conséquence: incidents manuels non comparables aux incidents automatiques.
- Correction: passer par le même manager de cycle de vie.
- Risque: changement des IDs/états attendus par la démo.
- Tests: incident manuel répété, résolution, réouverture.

## 28. Risques de doublons

### DUP-01 — HIGH

- `PlatformService.ingest_telemetry` crée des alertes puis appelle `SmartPortSiem.collect`; `mqtt_listener.process_message` crée aussi les alertes puis collecte par alerte.
- Un même événement peut donc produire alerte directe, événement SIEM, alerte SIEM et audit JSONL.
- Correction proposée: définir un seul propriétaire de création d’alertes et un identifiant de corrélation obligatoire.
- Risque: régression des tests qui vérifient les appels historiques.
- Tests: matrice transport x type x alerte, comptage exact en DB/JSONL.

### DUP-02 — HIGH

- `ActionDispatcher` et `IncidentManager` ont deux algorithmes de déduplication.
- La déduplication est en mémoire/lecture puis commit, sans contrainte unique SQL sur `dedup_key`.
- Deux workers concurrents peuvent créer deux incidents.
- Correction: transaction/contrainte et gestion d’intégrité.
- Risque: conflits avec historiques existants.
- Tests: deux créations concurrentes identiques.

## 29. Faux positifs ML possibles

### ML-01 — HIGH

- Fichier/fonction: `backend/ml/training.py`, `PredictionService.analyze`.
- Problème: modèles Isolation Forest entraînés sur distributions synthétiques étroites et contamination fixe 3%; pas de version/jeu de validation opérationnel associé.
- Conséquence: valeurs portuaires normales hors distribution classées anomalies.
- Correction: jeux de calibration représentatifs, seuils par domaine, validation temporelle et observabilité des scores.
- Risque: baisse du rappel des scénarios d’attaque.
- Tests: corpus normal réel simulé, corpus attaque, courbes précision/rappel.

### ML-02 — HIGH

- `decision_engine.make_decision` cumule legacy scalar, advanced models et network model; plusieurs prédictions du même événement deviennent plusieurs alertes `ml_anomaly`.
- Conséquence: sur-comptage et dispatch drone déclenché sur un signal isolé.
- Correction: agrégation par domaine avec seuil/hystérésis et une alerte canonique.
- Risque: changement du comportement observable de la démo.
- Tests: événement unique avec plusieurs modèles anormaux, nombre d’alertes et mission attendu.

### ML-03 — MEDIUM

- `PredictionService` utilise un `sensor_failure` basé sur absence de champ dans chaque message et état mémoire global.
- Conséquence: variations de transport, redémarrage ou perte de message peuvent ressembler à une panne capteur.
- Correction: état durable/heartbeat explicite et fenêtre de silence par type d’équipement.
- Risque: délai de détection plus élevé.
- Tests: silence réel, redémarrage, messages partiels et transports mixtes.

### ML-04 — MEDIUM

- `backend/main.py:get_device_health` calcule un score sur tout l’historique, sans fenêtre ni pondération temporelle.
- Conséquence: anciennes anomalies maintiennent un équipement en mauvais état indéfiniment.
- Correction: fenêtre configurable et distinction état courant/historique.
- Risque: score plus optimiste pendant une démonstration.
- Tests: anomalie ancienne, anomalie récente, zéro lecture.

## 30. Démarrage et déploiement

### DEPLOY-01 — CRITICAL

- `docker-compose.yml:env_file: .env`, `backend/core/config.py`.
- `.env` est requis par Compose mais l’application a des fallbacks dangereux si certaines valeurs manquent.
- Conséquence: stack soit non démarrable sans `.env`, soit démarrable avec sécurité faible.
- Correction: validation cohérente avant démarrage et séparation développement/production.
- Risque: les scripts actuels `run.py`/`startup.sh` peuvent diverger.
- Tests: `.env` absent, `.env.example`, configuration production minimale.

### DEPLOY-02 — HIGH

- `simulation/launch/port_simulation.launch.py`, `gazebo/launch/terminal.launch.py`.
- Chemins absolus vers anciens répertoires; dépendances ROS/Gazebo/TurtleBot non déclarées dans `requirements.txt` ni Compose.
- Conséquence: lancement impossible sur une autre machine et confusion avec le cœur MQTT.
- Correction: marquer explicitement ces lanceurs hors chemin final et ne pas les utiliser pour la démo cœur.
- Risque: scripts historiques moins utilisables.
- Tests: démarrage sans ROS2, démarrage MQTT drone seul.

### DEPLOY-03 — HIGH

- `backend/main.py:lifespan` démarre MQTT et UDP en arrière-plan; MQTT peut rester déconnecté sans faire échouer l’API; UDP avale le port indisponible.
- Conséquence: API « healthy » alors que l’ingestion principale est hors service; perte silencieuse de télémétrie.
- Correction: readiness séparant liveness, état broker explicite et métrique/alerte d’ingestion dégradée.
- Risque: orchestration plus stricte et démarrage plus lent.
- Tests: broker arrêté, port UDP occupé, reconnexion broker.

### DEPLOY-04 — MEDIUM

- `docker-compose.yml` n’impose aucun ordre de readiness; Compose affiche un avertissement de version obsolète.
- Conséquence: course backend/broker et bruit de déploiement.
- Correction: healthcheck Mosquitto/backend et `depends_on` conditionnel; retirer la clé `version` dans une future modification autorisée.
- Risque: compatibilité avec anciennes versions Compose.
- Tests: démarrage à froid, redémarrage séquentiel.

### DEPLOY-05 — MEDIUM

- `dashboard/build` est présent alors que `.gitignore` ignore les builds; le nom package et plusieurs docs utilisent encore `cyber-digital-twin`.
- Conséquence: artefact servi potentiellement différent de la source et identité projet incohérente.
- Correction: décider si build est généré au déploiement et mettre à jour les métadonnées lors d’une phase de modification autorisée.
- Risque: cache navigateur/CI et changement de branding.
- Tests: build reproductible, hash source/build, déploiement Docker.

## Synthèse de stabilisation prioritaire

1. Sécuriser les secrets JWT et les identifiants par défaut.
2. Protéger/authentifier le WebSocket et sécuriser MQTT.
3. Unifier ORM, base SQLite et chemin Data Lake sans suppression de données.
4. Unifier la création alertes/incidents et imposer l’idempotence SQL.
5. Séparer clairement l’API canonique versionnée des façades legacy.
6. Calibrer/agréger le ML avant tout dispatch drone automatique.
7. Rendre visibles les états degraded du broker/UDP et fiabiliser Compose.
8. Conserver le drone MQTT comme simulation externe; isoler ROS2/Gazebo/TurtleBot en documentation et outillage expérimental, hors cœur final.

## Verdict d’audit

- Architecture cible partiellement réalisée: **OUI pour le chemin MQTT -> FastAPI -> normalisation -> ML/cybersécurité -> SIEM -> SQLite/JSONL -> React**, mais avec deux implémentations concurrentes.
- Drone réel connecté au port: **NON**; le code observé implémente une simulation MQTT externe, ce qui correspond au contexte officiel.
- ROS2/Gazebo dans le cœur final: **NON souhaitable**, mais plusieurs imports et lanceurs legacy restent présents.
- Risque de données incohérentes selon le mode de démarrage: **ÉLEVÉ**.
- Risque de faux positifs ML et de doublons d’alertes/incidents: **ÉLEVÉ**.
- Risque sécurité par configuration par défaut: **CRITICAL**.
- Audit terminé sans modification de fichier existant.
