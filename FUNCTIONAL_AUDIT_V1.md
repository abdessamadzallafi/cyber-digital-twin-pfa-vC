# FUNCTIONAL AUDIT V1 — SecurIoT-Port

Audit strictement en lecture seule. Périmètre inspecté: `/home/abdo/Downloads/CyberPort`.

Date d’observation: 2026-09-19 (horloge de l’environnement). Les fichiers `.env` et credentials n’ont pas été lus; seuls `.env.example`, les noms de variables et la configuration structurelle ont été inspectés.

## Périmètre et méthode

- Lecture statique de `backend/`, `dashboard/src/`, `smart_port/`, `simulation/`, `scripts/`, `tests/`, `data/`, `data_lake/`, Compose/Dockerfiles et documentation.
- Extraction AST des routes FastAPI.
- Inventaire SQLite en URI `mode=ro`, avec `integrity_check`; aucune connexion en écriture.
- `docker compose config --quiet`, `docker compose ps`, `ss -ltnup`: inspection uniquement; aucun service lancé/redémarré.
- `pytest --collect-only -q -p no:cacheprovider`: 273 tests collectés, aucun test exécuté.
- État Git initial conservé comme préexistant: 11 fichiers modifiés, 3 fichiers non suivis; les rapports présents sont les seuls fichiers ajoutés par cette mission.

## A. Architecture réelle

### Chaîne opérationnelle réellement implémentée

```text
MQTT Mosquitto (port/#, drone/#)
  -> backend.mqtt_listener.on_message (thread Paho: JSON decode + enqueue)
  -> ingress_queue asyncio bornée
  -> mqtt_worker/process_message
  -> DeviceGateway.normalize
  -> Data Lake telemetry
  -> SQLite sensor_readings
  -> network_monitor + security.engine + legacy ML + advanced PredictionService
  -> Alert rows + SmartPortSiem events/correlation
  -> ActionDispatcher (incident dedup + cooldown + mission éventuelle)
  -> update_queue asyncio bornée
  -> /ws broadcast JSON
  -> dashboard App.jsx (WebSocket + polling 5 s)
```

HTTP et UDP rejoignent une chaîne parallèle:

```text
POST /api/v1/telemetry -> PlatformService.ingest_telemetry
UDP:9000 -> ingest_udp_payload -> PlatformService
PlatformService -> DataLakeWriter -> sensor_readings -> SiemService.evaluate
                         -> alerts -> SmartPortSiem audit event
```

Le drone est traité comme un simulateur externe MQTT (`simulation/drone_sim.py`), pas comme un équipement IoT réel. Le backend crée une mission, la persiste dans `missions`, publie `drone/mission`, puis reçoit potentiellement `drone/telemetry` et `drone/event`.

### Composants actifs

| Composant | Fichiers principaux | Dépendances/rôle | Statut | Importance |
|---|---|---|---|---|
| FastAPI principal | `backend/main.py`, `run.py` | FastAPI, SQLAlchemy, MQTT, UDP | Actif; façade root + lifespan | P0 |
| API versionnée | `backend/api/v1.py`, `siem.py`, `ai.py`, `drone.py`, `operations.py` | `backend.core.dependencies`, services canonisés | Actif mais peu consommé par le dashboard actuel | P0 |
| Compatibilité Smart Port | `smart_port/application/router.py`, `smart_port/config.py` | registre edge, health | Actif | P1 |
| Persistance canonique | `backend/database/` | SQLAlchemy, SQLite | Actif; `backend/database/__init__.py` initialise et upgrade le schéma | P0 |
| Modèles legacy | `backend/database.py`, `backend/models.py`, `backend/schemas.py` | ancienne base ORM | Import direct non observé dans le runtime canonique; risque de confusion | P1 legacy |
| MQTT ingress | `backend/mqtt_listener.py` | Paho, queues asyncio, Data Lake, SIEM | Actif | P0 |
| Normalisation | `backend/events/normalizer.py`, `smart_port/communication/device_gateway.py` | contrats CommonEvent + compatibilité plate | Actif; CommonEvent surtout additif et non consommé par tous les chemins | P1 |
| Détection | `backend/decision_engine.py`, `backend/security/`, `backend/network/`, `backend/ml/` | règles, Isolation Forest/joblib, corrélation | Actif; deux générations ML coexistent | P0/P1 |
| SIEM | `backend/siem/` | événements, corrélation 5 min, alert/incident/risk | Actif | P0 |
| Missions/drone backend | `backend/ros/`, `backend/services/action_dispatcher.py`, `backend/api/drone.py` | manager mémoire + SQLite + MQTT/ROS façade | Actif partiel | P0 |
| Simulateur drone | `simulation/drone_sim.py` | Paho MQTT, mouvement déterministe | Actif si lancé séparément; non déclaré comme service Compose | P1 |
| Data Lake | `smart_port/data/data_lake.py`, `backend/datalake/writer.py` | JSONL append-only | Actif; deux racines selon mode local/Docker | P0 |
| Dashboard | `dashboard/src/App.jsx` | React/Recharts, fetch, WebSocket | Actif; monolithique, polling + WS | P0 |
| Simulations capteurs/attaques | `simulation/*.py`, `attacks/*.py` | MQTT/UDP selon script | Externes; plusieurs produisent du random | P1 |
| ROS/Gazebo | `gazebo/`, `simulation/launch/`, `backend/ros/` | ROS optionnel avec fallback | Partiellement actif; `ROS2Interface.available` peut être faux | P1/legacy partiel |
| Rapports | `backend/report_generator.py`, `backend/reports/` | fpdf2, fichiers `reports/*.pdf` | Actif | P1 |

### Éléments legacy/contradictoires

- `backend/database.py` redéfinit les mêmes tables que `backend/database/`; le package `backend/database/` est l’import canonique quand `from backend.database import ...` est utilisé.
- `backend/ml/anomaly_detector.py` et `backend/ml/network_anomaly.py` sont des modèles scalar/legacy; `backend/ml/prediction_service.py` charge les bundles `advanced_*.pkl`. Les deux chemins alimentent `decision_engine`.
- API root (`/statistics`, `/devices`, `/missions`, etc.) et API versionnée (`/api/v1/...`) coexistent avec réponses et règles parfois différentes.
- `data/data_lake/` est la racine Docker via volume/config Compose; `data_lake/` à la racine est la valeur locale par défaut de `smart_port.config.Settings`. Les deux existent avec des contenus différents.
- `simulation/robot_sim.py`, ROS/Gazebo et anciennes façades robot sont hors de la boucle dashboard principale; l’identité canonique actuelle est `drone_01`.

## B. Dashboard React

### Pages/sections réellement présentes

`overview`, `devices`, `security`, `missions`, `incidents`, `timeline`, `datalake`, `reports`, toutes rendues dans `dashboard/src/App.jsx`. Il n’y a pas de router React: la navigation est un état local `tab`.

### Appels réseau et correspondance

| Élément UI | Fichier | Action | API appelée | Backend existant ? | Donnée réelle ? | Temps réel ? | Problème |
|---|---|---|---|---|---|---|---|
| Login | `App.jsx:110-120` | POST credentials | `POST /token` | Oui | Oui | Non | JWT stocké en `localStorage`; credentials démo par défaut dans `auth.py` si env absente |
| Rafraîchissement principal | `App.jsx:71-86` | polling 5 s | `/statistics`, `/risk`, `/devices`, `/incidents`, `/missions`, `/timeline`, `/drone/status`, `/api/v1/datalake` | Oui | Oui, sauf inventaire fallback | Non | 8+ requêtes périodiques et une requête `/health/{id}` par équipement |
| Carte équipement | `App.jsx:249-257` | clic | `/measures/{id}?limit=24` | Oui | Oui si mesure DB | Non | positions et labels de carte hardcodés; carte `port.jpeg` illustrative |
| Historique | `App.jsx:124-127`, `485-512` | GET + graphique | `/measures/{device_id}` | Oui | Oui | Non | valeur choisie `value ?? people_count`, donc certains types sont simplifiés |
| Scénario flood | `App.jsx:305-307`, `368-370` | POST | `/simulate/flood` | Oui | Oui si broker disponible | Non | crée 20 publications synchrones avec `sleep(0.1)`; l’UI ne montre pas le résultat/erreur |
| Scénario spoof | même | POST | `/simulate/spoof` | Oui | Oui si broker disponible | Non | endpoint envoie `value=999` et faux token |
| Valeur impossible | même | POST | `/simulate/impossible` | Oui | Oui si broker disponible | Non | envoie `-200`; détection dépend de règles/modèles |
| Déployer / créer mission | `App.jsx:205,208,299,394` | POST | `/force_mission/entrepot_E01` | Oui | Oui | Partiel | le dashboard ne consomme pas l’API versionnée `/api/v1/drone/missions`; retour d’erreur non affiché |
| Rapport | `App.jsx:128,212,480,508` | POST | `/report/{device_id}?anomaly_type=ml_anomaly` | Oui | fichier PDF réel | Non | fallback ouvre l’historique plutôt que produire immédiatement |
| Déconnexion | `App.jsx:122,190` | local state | aucun | N/A | Oui côté navigateur | Non | pas de révocation serveur, JWT reste valide jusqu’à expiration |
| Navigation latérale | `App.jsx:182-185` | setState | aucune | N/A | N/A | Non | fonctionnelle seulement comme navigation locale |
| Vue satellite | `App.jsx:242` | clic | aucune | Non | Non | Non | bouton sans `onClick` réel |
| Journal “Voir tout” | `App.jsx:282` | clic | aucune | Non | Non | Non | bouton décoratif |
| Notifications | `App.jsx:202` | clic | aucune | Non | compteur réel | Non | icône sans action |
| Fermer modal | `App.jsx:487-508` | state local | aucune | N/A | N/A | Non | fonctionnel localement |

### Données statiques, calculées ou artificielles

- `DEVICE_LABELS`, `DEVICE_TYPES`, `MAP_POSITIONS`, navigation et coordonnées de carte sont hardcodés dans `App.jsx`.
- L’écran login affiche `8`, `24/7`, `AI`, `DRONE` en statique.
- Si `/devices` renvoie vide, le dashboard affiche les 8 équipements de `DEVICE_LABELS` comme fallback, avec `100%` de santé par défaut: cela peut donner une impression d’inventaire réel alors qu’aucune télémétrie n’existe.
- Les compteurs “menaces” et “alertes” viennent de `/statistics`; le compteur incidents est calculé côté frontend à partir des incidents non résolus.
- Les événements WebSocket alimentent `events`, mais le message backend de drone porte `event: "drone_telemetry"`; le frontend teste `update.type === 'drone'`. La branche de mise à jour directe de `drone` ne correspond donc pas au contrat actuel. Le drone est quand même repollé toutes les 5 secondes.
- Aucun `Math.random()` dans `dashboard/src/App.jsx`; les données random sont dans certains simulateurs Python, pas dans l’UI React.
- Le dashboard n’appelle aucune route root `/dashboard`, `/alerts`, `/security/events`, `/api/v1/ops/*`, `/api/v1/siem/*`, `/api/v1/ai/predict` ou `/api/v1/drone/*`.

## C. API FastAPI

Préfixes: `smart_port/application/router.py` monte `/api/v1`; `backend/api/router.py` monte les routeurs versionnés; `backend/main.py` monte aussi de nombreuses routes root.

| Méthode | Route effective | Fichier/fonction | Dashboard ? | Modifie DB ? | Temps réel ? | Observation |
|---|---|---|---|---|---|---|
| POST | `/token` | `backend/main.py:login` | Oui | Oui indirectement: audit auth SIEM | Non | JWT bearer |
| GET | `/health` | `main.py:platform_healthcheck` | Non | Non | Non | DB + état MQTT |
| GET | `/health/{device_id}` | `main.py:get_device_health` | Oui | Non | Non | score dérivé anomalies/lectures |
| GET | `/statistics` | `main.py:get_statistics` | Oui | Non | Non | fenêtres d’activité et comptages |
| GET | `/dashboard` | `main.py:get_dashboard` | Non | Non | Non | ancienne vue root |
| GET | `/risk` | `main.py:get_risk_score` | Oui | Non | Non | fenêtre 5 min, seulement types cyber |
| POST | `/simulate/flood` | `main.py:simulate_flood` | Oui | Indirect | Non | publie MQTT |
| POST | `/simulate/spoof` | `main.py:simulate_spoof` | Oui | Indirect | Non | publie MQTT |
| POST | `/simulate/unknown` | `main.py:simulate_unknown` | Non | Indirect | Non | route existante mais aucun bouton |
| POST | `/simulate/impossible` | `main.py:simulate_impossible` | Oui | Indirect | Non | publie MQTT |
| POST | `/force_mission/{device_id}` | `main.py:force_mission` | Oui | Oui | Indirect MQTT | legacy façade vers DroneManager |
| GET | `/network/flow/{device_id}` | `main.py:get_network_flow` | Non | Non | Non | lit `sensor_readings`, pas `network_flows` |
| GET | `/network/stats` | `main.py:get_network_stats` | Non | Non | Non | lit alertes réseau |
| GET | `/drone/status` | `main.py:get_drone_status` | Oui | Non | Non | état principalement mémoire |
| GET | `/missions` | `main.py:get_missions` | Oui | Non | Non | 20 dernières missions |
| POST | `/report/{device_id}` | `main.py:create_report` | Oui | Fichier PDF | Non | rapport équipement |
| GET | `/equipments` | `main.py:get_equipments` | Non | Non | Non | distinct sensor_readings |
| GET | `/datalake` | `main.py:get_datalake` | Non | Non | Non | root protégé |
| GET | `/reports` | `main.py:list_reports_root` | Non | Non | Non | liste fichiers PDF |
| GET | `/measures/{device_id}` | `main.py:get_measures` | Oui | Non | Non | historique |
| GET | `/alerts` | `main.py:get_alerts` | Non | Non | Non | alertes root |
| GET | `/ml/anomalies` | `main.py:get_ml_anomalies` | Non | Non | Non | alertes `ml_anomaly` |
| GET | `/security/events` | `main.py:get_security_events` | Non | Non | Non | types cyber sélectionnés |
| POST | `/incidents` | `main.py:create_incident` | Non | Oui | Non | création manuelle sans dédup |
| GET | `/incidents` | `main.py:get_incidents` | Oui | Non | Non | liste |
| PUT | `/incidents/{id}/resolve` | `main.py:resolve_incident` | Non | Oui | Non | route existante, aucun bouton dashboard |
| GET | `/timeline` | `main.py:get_timeline` | Oui | Non | Non | fusionne alert/incident/mission |
| GET | `/devices` | `main.py:get_all_devices` | Oui | Non | Non | inventaire dérivé de mesures |
| GET | `/drone/missions` | `main.py:get_drone_missions` | Non | Non | Non | filtre `drone_01` en dur |
| GET | `/ws` | `main.py:websocket_endpoint` | Oui | Non | Oui | accepte sans vérifier JWT |
| GET | `/api/v1/platform/health` | `smart_port/application/router.py` | Non | Non | Non | health versionné |
| GET | `/api/v1/edge/devices` | même | Non | Non | Non | registre statique canonique |
| GET | `/api/v1/devices` | `backend/api/v1.py:list_devices` | Non | Non | Non | registre/lecture selon code |
| POST | `/api/v1/telemetry` | `backend/api/v1.py:ingest_telemetry` | Non | Oui | Non | chemin HTTP canonique |
| GET | `/api/v1/devices/{id}/telemetry` | `backend/api/v1.py:telemetry_history` | Non | Non | Non | API versionnée |
| GET | `/api/v1/datalake` | `backend/api/v1.py:datalake` | Oui | Non | Non | dashboard l’utilise |
| POST/GET | `/api/v1/siem/events` | `backend/api/siem.py` | Non | POST oui | Non | collecte/liste SIEM |
| GET | `/api/v1/siem/risk` | même | Non | Non | Non | risque SIEM |
| GET | `/api/v1/siem/incidents` | même | Non | Non | Non | incidents ouverts |
| POST | `/api/v1/siem/incidents/{id}/resolve` | même | Non | Oui | Non | résolution SIEM |
| GET/POST | `/api/v1/siem/reports` | même | Non | POST fichier | Non | rapports fenêtre SIEM |
| POST | `/api/v1/ai/predict` | `backend/api/ai.py` | Non | Non | Non | prédiction directe |
| GET/POST | `/api/v1/drone/status` + missions/start/return-home/telemetry/camera/tick | `backend/api/drone.py` | Non | créations/télémétrie selon route | Partiel | contrôle simulator/backend |
| GET | `/api/v1/ops/map` | `operations.py` | Non | Non | Non | registre statique + état drone |
| GET | `/api/v1/ops/datalake` | même | Non | Non | Non | catalogue |
| GET | `/api/v1/ops/network` | même | Non | Non | Non | lit `network_flows` |
| GET | `/api/v1/ops/security` | même | Non | Non | Non | types MITRE statiques + alertes |
| GET | `/api/v1/ops/mission` | même | Non | Non | Non | missions DB + état mémoire |
| GET | `/api/v1/ops/analytics` | même | Non | Non | Non | taux dérivé |
| GET | `/api/v1/ops/statistics` | même | Non | Non | Non | agrégat |
| GET | `/api/v1/ops/reports` | même | Non | Non | Non | fichiers PDF |
| GET | `/api/v1/ops/siem/timeline` | même | Non | Non | Non | SIEM events |

### Doublons de routes

- `GET /devices` est défini une fois dans `main.py` (`get_all_devices`); `GET /api/v1/devices` est distinct, pas collision effective.
- `GET /incidents/{id}/resolve` existe en root `PUT` et versionné `POST`; deux contrats pour la même intention.
- Datalake, reports, drone status, risk, missions et statistiques ont des façades root et versionnées.
- `/drone/status` root et `/api/v1/drone/status` lisent le même singleton `drone_manager`, mais sans contrat de réponse explicitement versionné.

## D. Authentification

```text
POST /token (OAuth2PasswordRequestForm)
  -> authenticate_user() dans backend/auth.py
  -> fake_users_db admin/operateur avec hash bcrypt généré au chargement
  -> create_access_token(sub, exp=60 min)
  -> dashboard localStorage token
  -> Authorization: Bearer <token> sur authFetch
  -> middleware jwt_auth_middleware pour les routes non publiques
  -> get_current_user dans les dépendances CurrentUser
```

Constats:

- JWT HS256, expiration explicite 60 minutes sur login; défaut générique 15 minutes si `create_access_token` est appelé sans delta ailleurs.
- Validation: signature, algorithme, `exp` via `python-jose`, présence `sub`, utilisateur connu.
- CORS: `allow_credentials=True`; si origins `*`, fallback explicite localhost:3000/8000. `OPTIONS` est bypassé.
- `/ws` est dans `PUBLIC_ENDPOINTS` et le handler WebSocket accepte immédiatement sans token; il n’y a donc pas d’authentification WebSocket malgré la protection REST.
- Credentials de démonstration: `admin`/`operateur`; si les variables manquent, `auth.py` retombe sur mots de passe locaux `admin`/`operateur`. C’est acceptable pour démo locale, bloquant pour une posture production.
- `.env.example` prévoit JWT, mots de passe et tokens drone; Compose référence `.env`. Le `.env` existe, mais sa valeur n’a pas été lue.
- L’audit d’authentification écrit des événements SIEM `login_success`/`login_failed`, ce qui peut créer du bruit SIEM; le middleware HTTP écrit également un événement pour chaque requête.

## E. MQTT et télémétrie

- Connexion backend: `settings.mqtt_host`, `mqtt_port`, TLS optionnel, reconnexion Paho 1–30 s.
- Souscriptions: `port/#` et `drone/#`, QoS configuré.
- `on_message` décode UTF-8/JSON objet; payload invalide est rejeté et compté; ajout de `mqtt_topic`; transfert thread-safe vers une queue bornée.
- Queue pleine: message perdu, `mqtt_errors` incrémenté. Queue worker pleine côté WebSocket: message dashboard perdu, `websocket_dropped` incrémenté.
- `process_message`: normalisation `DeviceGateway`, création CommonEvent, écriture Data Lake `telemetry`, branche drone séparée, sinon lecture DB, network monitor, décision, alertes, SIEM, commit, ActionDispatcher, broadcast.
- Topics drone: `drone/mission` (commande vers simulateur), `drone/telemetry`, `drone/gps`, `drone/camera`, `drone/event`.
- Topics capteurs: registre `smart_port/edge/device_registry.py`, forme `port/...`; le listener accepte toutefois tout `port/#` puis la validation identité génère `unknown_device`/`bad_token`/`wrong_topic`.
- Traitement des erreurs: JSON invalide et exceptions worker sont absorbés/loggés; erreur broker au démarrage est non fatale pour REST; perte de liaison Paho est marquée et reconnectée automatiquement.
- Télémétrie non-drone persistée dans `sensor_readings`; drone aussi persisté comme reading, mais explicitement exclu du `decision_engine` et de la ML dans `mqtt_listener.py`.
- La fonction `EventNormalizer.normalize` conserve les champs bruts et les métriques réseau non disponibles comme `None`; le pipeline historique continue à utiliser le dictionnaire normalisé plat.

## F. IA / ML

### Deux générations coexistantes

1. `backend/ml/anomaly_detector.py`: modèles legacy `temperature_model.pkl`, `humidity_model.pkl`, `vibration_model.pkl`, `smoke_model.pkl`, `camera_model.pkl`; entrée scalaire, prédiction `-1`, score `clamp(0.5 - decision*3, 0, 1)`.
2. `backend/ml/prediction_service.py`: bundles `advanced_*.pkl`, modèle par domaine, Isolation Forest attendu, features:
   - temperature/humidity: valeur;
   - battery: batterie;
   - drone_trajectory: x, y, dx, dy, speed;
   - sensor_failure: temps depuis dernier message + présence mesure;
   - flood_attack: packet_count + packet_size;
   - network_traffic: packet_count, bytes_total, avg_interval, throughput;
   - spoofing: valid_token, valid_topic;
   - unknown_device: appartenance au registre.

Le chargement est indépendant par modèle; en cas d’absence/corruption, fallback règles déterministes. `decision_engine` appelle les modèles legacy quand le type le permet, puis les modèles avancés, puis `network_anomaly.py`.

### Ce qui est réellement produit

- Une prédiction retourne `domain`, `anomalous`, `score`, `features`; dans la décision, les prédictions avancées sont converties en alertes `ml_anomaly` et le score maximum est diffusé en WebSocket.
- Une anomalie ML est actuellement convertie en `threat_level="red"` dans `decision_engine.py`, même si le domaine est un signal de comportement et non une preuve d’attaque. Il existe donc une séparation conceptuelle dans les noms (`ml_anomaly` vs cyber types), mais la gravité opérationnelle les fusionne souvent.
- `ActionDispatcher` reçoit `ml_anomaly` ou `network_attack`; certaines anomalies environnementales (`temperature`, `battery`, `sensor_failure`) peuvent déclencher une mission selon `mission_domains`.
- Le dashboard n’affiche ni les `features`, ni les modèles, ni la distinction legacy/advanced: il affiche principalement compteurs, score de risque, événements et valeur `anomaly_score` seulement dans le flux WS non rendu comme champ dédié.
- Risque de doublons: une même télémétrie peut recevoir alerte règle sécurité/réseau, anomalie legacy et plusieurs alertes avancées `ml_anomaly`; `decision_engine.py` ajoute chaque prédiction anormale séparément.

## G. SIEM / cybersécurité

### Chemins principaux

```text
payload MQTT/HTTP/UDP
  -> identity registry (unknown_device, bad_token, wrong_topic)
  -> network_monitor (network_flood, unknown_ip)
  -> security.engine (flood)
  -> decision_engine
  -> Alert rows dans alerts
  -> SmartPortSiem.collect(... manage_incident=False pour MQTT decision)
  -> siem_events + corrélation
  -> alert/incident SIEM seulement selon chemin et sévérité
  -> ActionDispatcher pour anomalie/attaque
```

Autres producteurs SIEM:

- chaque requête HTTP via `audit_http_requests` (`source=http`, `http_request`);
- login succès/échec via `auth.py`;
- ingestion HTTP `telemetry_ingested` via `PlatformService`;
- route `/api/v1/siem/events` directement;
- événements drone `drone_event` deviennent des `Alert` root mais ne passent pas par `SmartPortSiem.collect` dans `mqtt_listener.py`.

Corrélation: fenêtre 5 minutes par `device_id`; ≥3 échecs auth => high; réseau + capteur => high; ≥5 événements liés => medium; critical reste critical.

Risque de duplication important: `PlatformService` crée directement des `Alert` pour les résultats de `SiemService.evaluate`, puis ajoute un événement SIEM; la collecte SIEM peut elle-même créer une alerte/incident selon le chemin. `mqtt_listener` crée une alerte directe pour chaque `decision["alerts"]`, puis collecte SIEM avec `manage_incident=False`, puis ActionDispatcher crée/met à jour un incident séparément.

## H. Alertes

| Source | Type(s) | Créateur | Table | Dashboard | Risque duplication |
|---|---|---|---|---|---|
| identité capteur | `unknown_device`, `bad_token`, `wrong_topic` | `security.engine` via `decision_engine` | `alerts`, parfois `siem_events` | indirect `/statistics`, `/incidents` | Élevé avec SIEM/audit |
| flood temporel | `flood` | `security.engine` | `alerts` | compte `attacks` | Élevé avec `network_flood` |
| réseau | `network_flood`, `unknown_ip` | `network_monitor` | `alerts`, SIEM event | sécurité indirecte | Même télémétrie peut produire les deux |
| scalar ML | `ml_anomaly` | `anomaly_detector` | `alerts` | `/ml/anomalies` indirect | Élevé avec advanced ML |
| advanced ML | `ml_anomaly` par domaine | `prediction_service` | `alerts` | indirect | Plusieurs lignes pour un événement |
| legacy réseau ML | `ml_anomaly` | `network_anomaly` | `alerts` | indirect | Triple voie ML possible |
| drone event | `drone_*` | `mqtt_listener` | `alerts` | timeline/statistics partiel | ne passe pas toujours par SIEM |
| SIEM direct | event_type variable | `AlertManager` | `alerts` | routes SIEM non consommées | dépend de la collecte |
| auth/http | `login_*`, `http_request` | `auth.py`, middleware | `siem_events`, alert si sévérité haute | non directement | volume élevé, bruit |

Les incidents peuvent être créés par `IncidentManager` (SIEM) ou `ActionDispatcher.create_or_update_incident` (détection). La route manuelle `POST /incidents` ne déduplique pas.

## I. Missions

### États définis

`created`, `active`, `inspecting`, `returning_home`, `completed`, `aborted` dans `DroneMissionStatus`. `ActionDispatcher` accepte aussi `sent` et `in_progress` dans ses ensembles de compatibilité, mais ces états ne sont pas dans l’enum principal et aucune transition canonique ne les crée.

### Machine à états réellement implémentée

```text
[aucune mission]
   -- DroneManager.create_inspection / POST /api/v1/drone/missions ou /force_mission --> CREATED
   -- publish MQTT échoue --> ABORTED en DB puis exception
CREATED
   -- POST /api/v1/drone/missions/start --> ACTIVE (objet mémoire seulement)
ACTIVE
   -- tick + navigation vers waypoints --> FLYING dans DroneState
   -- dernier waypoint atteint --> INSPECTING
INSPECTING
   -- return_home / batterie basse --> RETURNING_HOME
RETURNING_HOME
   -- tick/navigation retour maison --> COMPLETED + DroneState idle/mission_id None
   -- erreur/arrêt simulateur --> ABORTED (simulateur) ou statut DB potentiellement non aligné
```

Détails:

- création: persiste `missions` status `created`, publie `drone/mission`, écrit Data Lake `missions`, initialise singleton mémoire.
- `start()` change l’objet `DroneMission` en `active` et state `flying`, mais ne met pas à jour la ligne SQLite `missions`.
- `tick()` publie telemetry/gps MQTT via backend ROS façade et avance de façon déterministe; il ne met pas directement à jour la DB de mission.
- `update_telemetry()` reflète le simulateur et peut changer l’état mémoire; `_update_mission_from_telemetry()` modifie la ligne DB si `mission_id`/status reçus.
- `simulation/drone_sim.py` a son propre worker déterministe, validation token/drone_id/waypoints, mouvement par pas, inspection/dwell, retour home et événements started/completed/aborted.
- cooldown: `settings.drone_mission_cooldown_seconds` défaut 60 s; une mission active ou une mission récente sur le même device bloque une nouvelle mission.
- dédup incident: fenêtre défaut 300 s, clé SHA-256 tronquée; la corrélation SIEM possède aussi sa propre logique, d’où deux chemins à surveiller.
- aucune interface dashboard ne démarre explicitement `/api/v1/drone/missions/start`, `/tick`, `/return-home`; le bouton “Déployer” crée et publie seulement.

## J. Drone simulator externe

Fichier principal: `simulation/drone_sim.py`. Aucun HTML/JS/CSS spécifique de simulateur drone n’a été trouvé dans le dépôt; le seul HTML visible est `dashboard/public/index.html`. Le “simulateur externe” effectivement livré est donc Python/MQTT, tandis que la visualisation drone est intégrée à `dashboard/src/App.jsx`.

| Donnée/fonction | Source | Classement |
|---|---|---|
| broker, port, drone_id, token, interval, step, seuil batterie | variables env + défauts | HARDCODED/configurable |
| état initial x/y/altitude/battery/status | `drone_sim.py:30-31` | SIMULATED_DETERMINISTIC |
| mission/waypoints | backend réel via MQTT `drone/mission` | REAL_BACKEND après création |
| validation token/drone_id/waypoints | simulateur | REAL logic |
| mouvement | pas bornés, `STEP_SECONDS` | SIMULATED_DETERMINISTIC |
| batterie | décrément fixe `0.1` par pas | SIMULATED_DETERMINISTIC |
| positions/altitude/status | état worker publié | SIMULATED_DETERMINISTIC |
| mission events | MQTT `drone/event` | REAL_BACKEND transport |
| `Math.random()` | absent dans `drone_sim.py`; recherches Python montrent random dans capteurs/caméra/fumée/vibration | RANDOM hors drone |
| ROS2/Gazebo | façade optionnelle côté backend | PARTIAL/OPTIONAL |
| WebSocket/REST direct | absent du simulateur | DISCONNECTED de l’UI directe; liaison via MQTT |
| bouton dashboard Déployer | POST root force mission | REAL création, mais pas pilotage lifecycle complet |

Architecture minimale recommandée, sans faux IoT: garder le drone comme “mission simulator boundary”; créer mission via API backend, publier commande MQTT signée, faire publier le simulateur `drone/telemetry` et `drone/event`, faire persister les transitions backend, puis diffuser un contrat WS unique. Ne pas ajouter le drone au registre capteurs générique pour lui faire simuler une télémétrie capteur; conserver `drone_id`, `mission_id`, `mission_status`, waypoint et provenance `simulator=true`.

## K. Temps réel

- Endpoint: `ws://<API>/ws`, serveur dans `backend/main.py:167-175`.
- Connexion acceptée sans header JWT ni query token.
- Serveur: `update_queue` -> tâche `broadcast()` -> `send_json` à tous les clients.
- Sources: MQTT télémétrie/événements et branche UDP/HTTP si elles publient dans la queue; le chemin HTTP `PlatformService` ne pousse pas directement dans `update_queue`, donc HTTP ingestion n’est pas intégralement temps réel.
- Format non unifié:
  - IoT: `{event:"telemetry", device_id, type, status, last_value, alerts, anomaly_score, network, action, timestamp}`;
  - drone telemetry: `{event:"drone_telemetry", device_id, ..., drone:{...}, telemetry:{...}}`;
  - drone event: `{event:"drone_event", device_id, payload:{...}}`.
- Reconnexion client: aucune stratégie explicite; `new WebSocket` une fois par token, fermeture au cleanup, pas de backoff/heartbeat client.
- Heartbeat serveur: absent; la boucle attend `receive_text()` mais le client ne transmet pas de ping applicatif.
- Consommation dashboard: met à jour `devices` et `events` si `device_id`; la mise à jour `drone` teste `type==='drone'`, incompatible avec `event==='drone_telemetry'`. Les chiffres principaux restent issus du polling 5 s.
- Queue bornée et pertes explicites; aucune reprise/replay WebSocket.

## L. Data Lake

- Writer: `smart_port/data/data_lake.py`, façade `backend/datalake/writer.py`.
- Format: JSONL append-only, lock thread local; jour UTC dans `YYYY-MM-DD.jsonl`.
- Streams: `telemetry`, `security`, `missions`, `network`, `logs`; alias `siem -> security`, `audit -> logs`.
- Écritures: MQTT telemetry, missions, security alerts, SIEM events, network/HTTP/UDP telemetry, logs de gateway.
- Catalogue: `lake_summary()` compte fichiers et lignes; utilisé par `/datalake`, `/api/v1/datalake`, `/api/v1/ops/datalake` et dashboard.
- Rotation: partition quotidienne, pas de compaction, rétention ou purge implémentée.
- Deux racines observées: `data/data_lake/` (Docker via `SMART_PORT_DATA_LAKE_PATH=/app/data/data_lake`) et `data_lake/` (défaut local). Cela peut produire deux historiques que l’UI ne voit pas simultanément.
- Dashboard affiche uniquement le catalogue, pas le contenu ni la provenance des événements.

## M. Database

### Runtime canonique

`backend/database/session.py` construit l’engine avec `settings.database_url`; `backend/database/models.py` définit:

`sensor_readings`, `alerts`, `network_flows`, `missions`, `incidents`, `siem_events`, `devices`, `drones`, `reports`, `logs`.

`backend/database/__init__.py` fait `Base.metadata.create_all()` et un upgrade non destructif de colonnes/index incidents/missions au chargement du module. Cette opération est dans le runtime; aucune migration n’a été exécutée par cet audit.

### Inventaire read-only observé

- `data/digital_twin.db`: intégrité SQLite `ok`; `sensor_readings=29069`, `alerts=47675`, `incidents=74`, `missions=35`, `siem_events=111545`; `devices=0`, `drones=0`, `network_flows=0`, `reports=0`, `logs=0`.
- `digital_twin.db`: intégrité `ok`; `sensor_readings=11180`, `alerts=8077`, `incidents=50`, `missions=157`, `siem_events=43639`; mêmes tables vides.
- `backup_stabilization/*.db` contient des copies correspondant à ces deux familles; non runtime.
- Les deux bases ont le même schéma canonique enrichi; elles ne sont pas équivalentes fonctionnellement (comptages différents).

### Usage réel des tables

- `sensor_readings`: source active de devices, historique, santé, statistiques, télémétrie.
- `alerts`: alertes règle/ML/SIEM et sécurité dashboard.
- `incidents`: ActionDispatcher, IncidentManager, routes incidents/timeline.
- `missions`: création DroneManager, listing dashboard, transitions telemetry.
- `siem_events`: SmartPortSiem, routes SIEM/timeline, audit HTTP/auth.
- `network_flows`: modèle/API ops, mais le chemin MQTT actuel conserve surtout les métriques en mémoire et lit `sensor_readings` pour `/network/flow`; table observée vide.
- `devices`, `drones`, `reports`, `logs`: modèles présents mais pas alimentés par le chemin principal observé (les rapports sont des fichiers, logs Data Lake).
- `backend/database.py`: architecture ORM legacy; ne pas supprimer sans vérifier les importeurs externes.

## N. Docker et configuration

- Services Compose: `mosquitto`, `backend`, `dashboard`.
- Ports host: 1883, 8000, 3000.
- Backend dépend de Mosquitto; dashboard dépend du backend.
- Volumes backend: `./data:/app/data`, `./reports:/app/reports`; DB `/app/data/digital_twin.db`; Data Lake `/app/data/data_lake`.
- `env_file: .env` est requis; `.env.example` documente JWT, mots de passe, tokens et MQTT/UDP.
- Dockerfiles présents: `backend/Dockerfile`, `dashboard/Dockerfile`.
- `docker compose config --quiet`: OK avec avertissement Compose v2 sur `version: '3.8'` obsolète.
- `docker compose ps`: stack déjà existante et active depuis 4 h au moment de l’inspection; aucun démarrage/restart réalisé.
- ports 3000/8000/1883 occupés par cette stack; un second `compose up` aurait risqué un conflit de bind.

## O. Tests

### Groupes présents

| Fichiers | Couverture | Non couvert/limite |
|---|---|---|
| `test_event_normalizer.py`, `test_http_common_event.py`, `test_udp_common_event.py` | contrats CommonEvent, transports, conservation payload, bool/GPS/network metadata | pas de test d’intégration broker réel |
| `test_mqtt_listener_event.py`, `test_mqtt_safety.py`, `test_main_mqtt.py` | séparation drone/IoT, queue logique, publish simulation | reconnexion broker réelle, saturation longue durée |
| `test_action_dispatcher.py` | dedup incident, cooldown, une mission active | cohérence DB/mémoire après redémarrage |
| `test_drone_simulator.py` | validation, worker unique, mouvement/inspection/retour | aucun HTML/JS; intégration backend+MQTT réelle hors probe |
| `test_siem_report_regression.py`, `test_final_stabilisation_predict_reports.py` | rapports SIEM/PDF et prédiction sérialisable | génération concurrente et stockage |
| `test_stabilisation_e8.py` | régressions de télémétrie, bool, GPS, SIEM | parcours UI complet |

273 tests ont été collectés avec succès; ils n’ont pas été exécutés afin de respecter l’audit read-only et d’éviter les effets de bord possibles (PDF, DB, Data Lake, cache). Le test `test_siem_report_regression.py` annonce explicitement la création d’un PDF et n’a donc pas été lancé.

## P. Matrice fonctionnelle finale

| FEATURE | REAL | PARTIAL | FAKE/STATIC | RANDOM | DISCONNECTED | LEGACY | PRIORITY |
|---|---:|---:|---:|---:|---:|---:|---|
| Login JWT REST | Oui |  |  |  |  |  | P0 |
| Auth WebSocket |  | Oui |  |  |  |  | P0 |
| Ingestion MQTT IoT -> DB | Oui |  |  |  |  |  | P0 |
| Ingestion HTTP/UDP -> DB | Oui |  |  |  |  |  | P1 |
| Normalisation CommonEvent |  | Oui |  |  |  |  | P1 |
| Détection règles cyber | Oui |  |  |  |  |  | P0 |
| ML avancé |  | Oui |  |  |  |  | P1 |
| Séparation anomalie ML/attaque |  | Oui |  |  |  |  | P0 |
| SIEM événements/corrélation |  | Oui |  |  |  |  | P0 |
| Alertes sans duplication |  |  |  |  |  | Oui risque | P0 |
| Incidents dédupliqués |  | Oui |  |  |  |  | P0 |
| Mission backend persistée |  | Oui |  |  |  |  | P0 |
| Mission simulator MQTT | Oui |  |  |  |  |  | P1 |
| Mission lifecycle DB complet |  | Oui |  |  |  |  | P0 |
| Drone dashboard live |  | Oui |  |  | Oui contrat WS |  | P1 |
| Drone HTML/JS externe |  |  |  |  | Oui |  | P1 |
| Carte port |  |  | Oui positions/image |  |  |  | P2 |
| Inventaire équipements |  | Oui | Oui fallback 8 devices |  |  |  | P1 |
| Data Lake catalogue | Oui |  |  |  |  |  | P1 |
| Data Lake unique en local/Docker |  | Oui |  |  | Oui split roots |  | P0 |
| Rapports PDF | Oui |  |  |  |  |  | P1 |
| Bouton Vue satellite |  |  | Oui |  | Oui |  | P2 |
| Bouton Voir tout journal |  |  | Oui |  | Oui |  | P2 |
| Notifications |  |  | Oui compteur |  | Oui |  | P2 |
| Simulateurs capteurs |  | Oui |  | Oui |  |  | P1 |
| ROS2/Gazebo |  | Oui |  |  |  | Oui/optionnel | P2 |

## Q. TOP 10 problèmes réels

1. WebSocket public sans authentification et sans contrôle de connexion.
2. Contrat WS drone incohérent: backend `event=drone_telemetry`, frontend teste `type=drone`.
3. Deux racines Data Lake (`data/data_lake` et `data_lake`) selon mode d’exécution.
4. Deux familles ORM/database et schémas legacy coexistent.
5. Deux générations ML + réseau legacy peuvent produire plusieurs alertes pour un même événement.
6. Anomalie ML avancée élevée directement au niveau `red`, ce qui mélange anomalie comportementale et attaque cyber.
7. Alertes directes, alertes SIEM et incidents ActionDispatcher sont des chemins multiples avec risque de duplication.
8. Lifecycle mission partagé entre état mémoire et DB; `start/tick` ne synchronisent pas toujours la ligne `missions`.
9. Dashboard utilise des fallbacks statiques (8 appareils, santé 100 %, carte hardcodée) qui peuvent présenter des données non observées.
10. Plusieurs boutons visibles n’ont aucune action réelle; aucun feedback utilisateur robuste sur erreurs de mutation.

## R. TOP 10 fonctionnalités déjà opérationnelles

1. Login REST avec JWT expirant et hash bcrypt.
2. Ingestion MQTT JSON avec queue bornée et reconnexion Paho.
3. Persistance des lectures et alertes SQLite.
4. Normalisation et conservation des payloads bruts.
5. Détection identité/topic/token et détection flood/IP.
6. Isolation Forest legacy/advanced chargée indépendamment avec fallback.
7. SIEM event store, corrélation 5 minutes et calcul de risque.
8. Dedup incident/cooldown mission dans ActionDispatcher.
9. Création mission réelle, persistance, publication MQTT et simulateur déterministe.
10. Data Lake JSONL append-only, catalogue dashboard et rapports PDF.

## S. Recommandations minimales

### À supprimer ou masquer de la démo

- Boutons sans implémentation: “Vue satellite”, “Voir tout le journal”, notifications cliquables.
- Présentation d’un drone HTML/JS comme équipement IoT: conserver la frontière “simulateur de mission externe”.
- Affichage fallback d’équipements comme s’ils étaient actifs lorsque `/devices` est vide.
- Exposition de façades legacy dans le parcours de soutenance si la route versionnée canonique est choisie.

### À connecter

- Dashboard vers `/api/v1/drone/*` pour créer/démarrer/retourner et afficher le statut canonical.
- Unifier la réponse WebSocket et brancher `drone_telemetry` sur l’état drone.
- Ajouter l’action de résolution incident au dashboard si la gestion d’incident est revendiquée.
- Choisir une seule racine Data Lake configurée pour local et Docker.

### À corriger

- Authentifier le WebSocket avec un mécanisme compatible navigateur (cookie HttpOnly ou ticket court; ne pas mettre un JWT durable dans l’URL).
- Définir un seul producteur d’alerte ou une clé de déduplication événementielle commune.
- Définir explicitement la politique: anomalie ML = signal; attaque cyber = classification SIEM séparée.
- Synchroniser chaque transition mission en DB et imposer une machine d’états unique.
- Remplacer les fallback UI silencieux par un état “inventaire indisponible”.

### À rendre temps réel

- état drone, transitions mission, incidents nouveaux, compteurs utiles.
- utiliser polling seulement comme resynchronisation de secours.
- ajouter reconnexion/backoff et heartbeat côté WebSocket.

### Données déterministes

- drone: déjà déterministe; conserver pas, waypoints, batterie, timestamps de provenance.
- démonstration soutenance: privilégier scénarios capteurs/attaques scriptés plutôt que `random` de `camera_sim.py`, `detecteur_fumee.py`, `capteur_vibration.py`.
- ne pas afficher de “données live” statiques si aucune mesure n’est présente.

## T. Plan de correction optimal, sans gros refactoring

1. Geler le contrat fonctionnel cible: `/api/v1`, un schéma WS, une racine Data Lake, et le statut du drone comme simulateur externe.
2. Corriger le contrat WS dashboard/backend, ajouter reconnexion et authentification contrôlée; conserver le polling de secours.
3. Brancher les boutons mission sur le lifecycle réellement supporté et afficher les erreurs/409/aborted.
4. Supprimer les fallbacks trompeurs et marquer explicitement les éléments statiques.
5. Choisir la voie d’alerte canonique; ajouter une clé d’événement/dedup commune avant toute suppression de tables ou modules.
6. Séparer score ML, anomalie, menace cyber et incident dans les réponses/API/UI.
7. Synchroniser les transitions de mission mémoire/SQLite et tester redémarrage/reprise.
8. Unifier le chemin Data Lake par configuration et ajouter un test de provenance local/Docker.
9. Réduire progressivement les façades root/legacy après mesure des consommateurs, sans supprimer `backend/database.py` ou modèles historiques à l’aveugle.
10. Exécuter ensuite les tests d’intégration isolés avec DB/Data Lake temporaires; cette étape est hors du présent audit read-only.

## Conclusion

La plateforme possède une chaîne réelle MQTT -> stockage -> détection -> SIEM -> mission -> MQTT drone -> WebSocket/polling. Elle est donc substantiellement fonctionnelle, mais la démonstration n’est pas encore une chaîne parfaitement cohérente de bout en bout: le dashboard mélange contrats root/versionnés, statique et réel; le drone est réel comme simulateur MQTT mais seulement partiellement synchronisé avec l’UI; alertes/ML/SIEM ont plusieurs producteurs; deux racines Data Lake et deux ORM subsistent.

FUNCTIONAL_AUDIT_COMPLETE
MODIFICATIONS_CODE = 0
MODIFICATIONS_DATABASE = 0
