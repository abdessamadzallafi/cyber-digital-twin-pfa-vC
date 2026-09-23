# TARGETED_FUNCTIONAL_INSPECTION_V1

Inspection ciblée en lecture seule du projet `/home/abdo/Downloads/CyberPort`.

Point de départ utilisé: `FUNCTIONAL_AUDIT_V1.md` et `FUNCTIONAL_AUDIT_V1.json`.
Périmètre limité à WebSocket, missions/drone, fallbacks dashboard, création d’alertes et chaîne ML.

## 1. WEBSOCKET

### Backend exact

- Fichier: `backend/main.py`
- Endpoint: `@app.websocket("/ws")`, lignes 167-175.
- Fonction: `websocket_endpoint(websocket)`.
- Authentification actuelle: aucune. Le middleware HTTP ne protège pas le handshake WebSocket de manière équivalente; `/ws` est aussi dans `PUBLIC_ENDPOINTS` (`backend/auth.py`). Le handler fait directement `await websocket.accept()`.
- Connexion enregistrée dans le set global `connected_websockets`.
- Réception client: `await websocket.receive_text()` uniquement. Le contenu reçu n’est pas interprété.
- Diffusion: `broadcast()` attend `update_queue.get()` puis appelle `ws.send_json(msg)` pour chaque client.
- Pas de vérification JWT, pas de heartbeat applicatif, pas de replay, pas de reconnexion serveur.
- Si la `update_queue` est pleine, le message est abandonné par `mqtt_listener._publish_dashboard` et `metrics["websocket_dropped"]` est incrémenté.

### Événements backend envoyés

#### Événement IoT / capteur

Producteur: `backend/mqtt_listener.py:173-176`, après `make_decision()`.

```json
{
  "event": "telemetry",
  "device_id": "<id>",
  "type": "<device_type>",
  "status": "green|red",
  "last_value": "<value_or_status>",
  "alerts": ["<message>"],
  "anomaly_score": 0.0,
  "network": {
    "ip_src": "...",
    "mac_src": "...",
    "packet_count": 0,
    "bytes_total": 0,
    "avg_interval": 0.0,
    "throughput": 0.0,
    "duration": 0.0
  },
  "action": null,
  "timestamp": 0.0
}
```

Destination: `update_queue` → `broadcast()` → tous les clients `/ws` → dashboard.

#### Événement télémétrie drone

Producteur: `backend/mqtt_listener.py:127-131`, depuis `_process_drone_telemetry()`.

```json
{
  "event": "drone_telemetry",
  "device_id": "drone_01",
  "type": "drone|drone_gps|camera_stream",
  "status": "idle|flying|...",
  "x": 0.0,
  "y": 0.0,
  "altitude": 0.0,
  "battery": 100.0,
  "mission_id": "...",
  "mission_status": "created|active|inspecting|returning_home|completed|aborted",
  "telemetry": {"<payload MQTT original>" : "..."},
  "drone": {"<DroneManager.status()>" : "..."},
  "timestamp": 0.0
}
```

Destination: `update_queue` → `/ws` → dashboard.

#### Événement opérationnel drone

Producteur: `backend/mqtt_listener.py:144-149`, quand le type normalisé vaut `drone_event`.

```json
{
  "event": "drone_event",
  "device_id": "drone_01",
  "payload": {
    "device_id": "drone_01",
    "type": "drone_event",
    "event_type": "mission_started|mission_completed|mission_aborted|mission_rejected",
    "message": "...",
    "mission_id": "...",
    "timestamp": 0.0
  }
}
```

Destination: `update_queue` → `/ws` → dashboard.

### Dashboard exact

- Fichier: `dashboard/src/App.jsx`.
- URL: `WS_URL = process.env.REACT_APP_WS_URL || API.replace(/^http/, 'ws') + '/ws'`, lignes 5-6.
- Connexion: lignes 96-108, `new WebSocket(WS_URL)` lorsque `token` existe.
- Token envoyé: non. Le token est utilisé dans les appels REST via `authFetch`, mais aucun header/token/query parameter n’est ajouté à la connexion WebSocket.
- Format attendu dans le handler: JSON décodé par `JSON.parse(data)`.
- Handler principal: `ws.current.onmessage`.

Logique actuelle:

```text
update.type === 'drone'
  -> setDrone(previous => ({...previous, ...update}))

si update.device_id
  -> setDevices(...update)
  -> prepend update dans events
```

Il n’existe pas de handler dédié pour `update.event === 'drone_telemetry'` ou `update.event === 'drone_event'`.

### Incompatibilités WebSocket précises

1. Backend drone envoie `event: "drone_telemetry"`; dashboard teste `update.type === "drone"`. La branche de mise à jour directe du drone ne s’exécute pas.
2. Le backend envoie aussi `type: "drone"` dans le payload de télémétrie drone car `type` est copié depuis la donnée MQTT. Cela ne suffit pas à résoudre le problème: le handler fusionne alors le message dans `devices`, mais la détection `update.type === 'drone'` peut être vraie uniquement pour certains messages et ne vérifie pas `event`.
3. Pour `drone_event`, `type` n’est pas au niveau racine; il se trouve dans `payload.type`. Le dashboard ne traite pas la transition métier `mission_started/completed/aborted`.
4. Le dashboard ne consomme pas `payload.mission_status` pour calculer une machine d’état locale; il dépend surtout de `GET /drone/status` toutes les 5 secondes.
5. Aucun mécanisme de reconnexion/backoff client.
6. Le WebSocket est accepté sans authentification malgré le token REST.
7. Le serveur peut perdre des messages sur queue pleine; aucun rattrapage par séquence/id n’existe.

### Contrat actuel sous forme source → event → payload → destination

```text
MQTT port/#
  → event="telemetry"
  → {device_id,type,status,last_value,alerts,anomaly_score,network,action,timestamp}
  → update_queue → /ws → App.jsx.onmessage → devices/events

MQTT drone/telemetry|drone/gps|drone/camera
  → event="drone_telemetry"
  → {device_id,type,status,x,y,altitude,battery,mission_id,mission_status,telemetry,drone,timestamp}
  → update_queue → /ws → App.jsx.onmessage
  → devices/events; mise à jour drone directe non fiable car le test utilise type="drone"

MQTT drone/event
  → event="drone_event"
  → {device_id,payload:{event_type,mission_id,message,timestamp,...}}
  → update_queue → /ws → App.jsx.onmessage
  → devices/events seulement; aucune transition mission dashboard dédiée

REST GET /drone/status
  → réponse DroneManager.status()
  → App.jsx.refresh toutes les 5 s
  → setDrone

REST POST /force_mission/{device_id}
  → création mission backend
  → MQTT drone/mission
  → simulateur drone
  → MQTT drone/telemetry + drone/event
  → backend DB/WS
```

## 2. MISSIONS / DRONE

### Fichiers inspectés

- `backend/services/action_dispatcher.py`
- `backend/ros/drone_manager.py`
- `backend/ros/drone_models.py`
- `backend/ros/mission_planner.py`
- `backend/ros/waypoint_navigation.py`
- `backend/ros/inspection_mission.py`
- `backend/api/drone.py`
- `backend/main.py`
- `backend/mqtt_listener.py`
- `backend/database/models.py`
- `simulation/drone_sim.py`

### États réellement déclarés

`backend/ros/drone_models.py:8-14` définit:

- `created`
- `active`
- `inspecting`
- `returning_home`
- `completed`
- `aborted`

`ActionDispatcher.ACTIVE_MISSION_STATUSES` ajoute aussi `sent` et `in_progress` par compatibilité, mais ces deux valeurs ne sont pas dans `DroneMissionStatus` et ne sont pas créées par le manager principal.

### Tableau des transitions

| STATUS / transition | Fichier/fonction responsable | Persistance DB ? | Notification WebSocket ? | Notification simulateur ? |
|---|---|---:|---:|---:|
| aucune → `created` | `DroneManager.create_inspection()` lignes 35-64; `POST /api/v1/drone/missions`; `/force_mission/{device_id}` | Oui, insertion `missions.status="created"` lignes 48-51 | Non directement | Oui, publication `drone/mission` ligne 52 |
| `created` → `aborted` si publication MQTT échoue | `DroneManager.create_inspection()` lignes 52-55 | Oui, update DB `aborted` | Non directement | Non; le simulateur n’a pas reçu la mission |
| `created` → `active` | `DroneManager.start()` + `InspectionMission.begin()` | Non dans cette fonction | Non directement | Non; cette voie API pilote le manager, pas le simulateur MQTT |
| `created/active` → `flying` | `DroneManager.start()` met `DroneState.status="flying"`; `WaypointNavigator.update()` | Non directement | Oui seulement si un publish télémétrie suit | Oui indirectement par télémétrie MQTT si `tick()` est utilisé |
| `active/flying` → `inspecting` | `WaypointNavigator.update()` après arrivée dernier waypoint; simulateur `_fly()` après chaque waypoint | DB seulement si télémétrie simulator reçue avec `mission_status` | Oui pour télémétrie; pas d’événement WS métier direct | Oui: simulateur publie télémétrie `mission_status="inspecting"` |
| `active/inspecting` → `returning_home` | `DroneManager.return_home()`, batterie dans `tick()`, simulateur `_fly()` ligne 142 | DB seulement via télémétrie simulator | Oui via télémétrie | Oui dans simulateur |
| `returning_home` → `completed` | `WaypointNavigator.update()` ou simulateur `_fly()` retour maison | Manager seul: pas forcément; simulator: `_update_mission_from_telemetry` peut mettre DB `completed` | Simulator publie `drone/event event_type=mission_completed` puis télémétrie idle | Oui |
| mission active → `aborted` | simulateur worker sur arrêt/échec; publish mission initial échoué | Initial publish: oui; worker simulator: backend ne traite pas `drone_event` comme mise à jour mission DB | `drone_event` broadcasté | Oui `mission_aborted` |
| mission active → `completed` via `status="idle"` sans mission_id | `_update_mission_from_telemetry()` lignes 107-111 | Oui, première mission active du drone passe à `completed` | Le message drone telemetry est broadcasté | Le simulator est source du message |

### State machine réelle

```text
NONE
  └─ create_inspection / force_mission / POST /api/v1/drone/missions
       └─ DB missions=created
       └─ MQTT drone/mission
       └─ manager memory=created

CREATED
  ├─ POST /api/v1/drone/missions/start
  │    └─ memory mission=active, DroneState=flying
  ├─ simulateur reçoit commande
  │    └─ memory simulator mission_status=active, state=flying
  └─ échec publish
       └─ DB=aborted

ACTIVE / FLYING
  ├─ navigation vers waypoints
  ├─ batterie basse / return-home
  │    └─ RETURNING_HOME
  └─ dernier waypoint
       └─ INSPECTING

INSPECTING
  └─ retour normal ou commande retour
       └─ RETURNING_HOME

RETURNING_HOME
  └─ arrivée HOME
       └─ COMPLETED, state idle, mission_id souvent null côté simulator

TOUT ÉTAT WORKER
  └─ arrêt/échec simulator
       └─ ABORTED côté simulator
```

### Divergences mémoire / DB / MQTT / dashboard

- Mémoire: `DroneManager.mission` et `DroneManager.state` sont des singletons process. Ils disparaissent au redémarrage.
- DB: la création est persistée dans `missions`; `start()` et `tick()` ne mettent pas directement à jour la ligne `missions`. La DB dépend donc du retour télémétrique du simulateur pour refléter plusieurs transitions.
- MQTT: le simulateur est piloté par `drone/mission` et publie les états sur `drone/telemetry`/`drone/event`. Le backend ingère la télémétrie et met à jour la DB pour `mission_id + mission_status` ou pour `status=idle`.
- Dashboard: création via `/force_mission/{device_id}`; aucun appel à `/api/v1/drone/missions/start`, `/return-home` ou `/tick`; état principalement via polling `/drone/status`; WS drone mal consommé.
- Le champ SQL physique est `robot_id`, exposé Python comme `Mission.drone_id`; la mission backend utilise `drone_id=settings.drone_id`.
- `drones` n’est pas la source runtime de l’état: le manager mémoire est utilisé; le modèle `Drone` n’est pas alimenté par ce chemin.
- Les événements `mission_started`, `mission_completed`, `mission_aborted` du simulator sont stockés comme alertes `drone_<event_type>` avec sévérité `info`, mais ne mettent pas directement à jour `missions.status` dans `mqtt_listener.py`.

## 3. DASHBOARD FALLBACKS

| FILE | LINE | VARIABLE | CURRENT BEHAVIOR | DATA SOURCE | PROBLEM | SAFE REPLACEMENT |
|---|---:|---|---|---|---|---|
| `dashboard/src/App.jsx` | 5 | `API` | fallback `http://localhost:8000` | valeur locale | peut pointer vers mauvais backend | afficher une erreur de configuration plutôt qu’un endpoint implicite en production |
| `dashboard/src/App.jsx` | 6 | `WS_URL` | dérive `API` en `ws` + `/ws` | valeur locale | masque une configuration WS absente | exiger une URL configurée ou afficher “temps réel indisponible” |
| `dashboard/src/App.jsx` | 38 | `number(value)` | `Number(value || 0)` | valeur frontend | null/undefined deviennent 0; perte de distinction “pas de donnée” | retourner `—` pour valeur absente |
| `dashboard/src/App.jsx` | 41 | `token` | `localStorage.getItem('token') || ''` | navigateur | état connecté apparent jusqu’à échec API; pas de validation locale | valider réponse 401 et vider explicitement session |
| `dashboard/src/App.jsx` | 49 | `stats` | tous compteurs initialisés à 0 | frontend | écran initial affiche zéro avant confirmation backend | afficher un état `loading` |
| `dashboard/src/App.jsx` | 51 | `risk` | `{risk_score:0, level:'Low'}` | frontend | peut présenter risque faible avant réponse réelle | afficher `—`/`loading` |
| `dashboard/src/App.jsx` | 57 | `drone` | `{x:10,y:10,status:'idle',battery:100,...}` | frontend | position/batterie initiales artificielles | état `unknown` jusqu’à `/drone/status` |
| `dashboard/src/App.jsx` | 125 | historique `value` | `row.value ?? row.people_count ?? 0` | DB puis fallback frontend | valeur 0 peut être fausse pour ligne sans métrique | conserver null et afficher absence |
| `dashboard/src/App.jsx` | 145-168 | cartes login | `8`, `24/7`, `AI`, `DRONE` | hardcoded JSX | chiffres/promesses non issus de l’API | supprimer ou alimenter via endpoint de capacités réel |
| `dashboard/src/App.jsx` | 174 | `activeEvents` | fallback sur `timeline.slice(0,5)` si WS vide | API timeline | peut faire passer historique pour flux live | label “derniers événements” et état live séparés |
| `dashboard/src/App.jsx` | 222 | carte équipements | `stats.active_devices`, `stats.total_devices` | `/statistics` | réel mais dépend des lectures reçues, pas du registre | distinguer “vus dans télémétrie” et “enregistrés” |
| `dashboard/src/App.jsx` | 225 | risque | `Number(risk.risk_score||0)` + labels par défaut | `/risk` puis frontend | 0 affiché si API absente | état indisponible explicite |
| `dashboard/src/App.jsx` | 251 | `devices[id] || {}` | objet vide pour chaque device hardcodé | WS uniquement | équipements non observés affichés sur carte | utiliser registre `/api/v1/edge/devices` + statut `unknown` |
| `dashboard/src/App.jsx` | 260 | position drone | `robot.x || 10`, `robot.y || 10` | API/WS puis fallback | position 0 est remplacée par 10; position fausse au départ | tester `null/undefined`, conserver 0 |
| `dashboard/src/App.jsx` | 277 | libellé événement | `... || 'Événement système'`; valeur `... || 'Nouvelle activité détectée'` | WS/timeline | message générique présenté comme événement | afficher “donnée indisponible” sans inventer activité |
| `dashboard/src/App.jsx` | 296 | batterie | `robot.battery || 0` | API/WS puis 0 | batterie absente rendue à 0 | `--` tant qu’inconnue |
| `dashboard/src/App.jsx` | 316 | `list` | fallback `Object.keys(DEVICE_LABELS)` | 8 IDs hardcodés | liste d’équipements affichée sans DB/registre | utiliser `/api/v1/edge/devices`; vide = “inventaire indisponible” |
| `dashboard/src/App.jsx` | 327 | état device | `device.online === false ? 'red' : 'green'` | API devices puis fallback | absence d’état considérée opérationnelle | `unknown` sans mesure récente |
| `dashboard/src/App.jsx` | 331 | zone | `'Terminal principal'` | API puis fallback | zone inventée | afficher `—` |
| `dashboard/src/App.jsx` | 332 | dernière mesure | `'—'` | API/WS | acceptable mais absence non distinguée dans style | conserver `—` avec état explicitement “non observé” |
| `dashboard/src/App.jsx` | 333 | health | `device.health_score ?? 100` | API health puis fallback | santé parfaite par défaut | `—`/unknown tant que non calculée |
| `dashboard/src/App.jsx` | 349 | risk security | `risk.risk_score ?? 0` | API | faux faible si réponse absente | placeholder loading/error |
| `dashboard/src/App.jsx` | 389 | mission drone | texte “attend sa prochaine mission” si `mission_id` absent | état local | peut masquer une mission DB non chargée | afficher “état non chargé” séparément de “idle” |
| `dashboard/src/App.jsx` | 390 | batterie mission | `drone.battery || 0` | API/WS puis fallback | batterie inconnue = 0 | `--` |
| `dashboard/src/App.jsx` | 391 | position mission | `Number(drone.x || 0)` | API/WS puis fallback | position inconnue = 0 | `—` |
| `dashboard/src/App.jsx` | 403 | mission status | `mission.status || 'pending'` | `/missions` | statut non fourni transformé en pending non contractuel | afficher “inconnu” |
| `dashboard/src/App.jsx` | 404 | date mission | `'—'` si `created_at` absent | DB | acceptable, mais aucune provenance affichée | garder `—` |
| `dashboard/src/App.jsx` | 424-425 | incident severity/status | `medium` / `open` par défaut | `/incidents` | état réel remplacé par défaut | afficher unknown et signaler réponse incomplète |
| `dashboard/src/App.jsx` | 441-443 | timeline type/time | `'À l’instant'`, `'alert'`, `'événement'` par défaut | `/timeline` | historique peut sembler live | afficher “date/type inconnu” |
| `dashboard/src/App.jsx` | 455 | Data Lake retention | `'append-only'` | API puis fallback | valeur probablement vraie mais non vérifiée | afficher loading/error avant API |
| `dashboard/src/App.jsx` | 461 | Data Lake format | `'jsonl'` | API puis fallback | prétention statique si API absente | utiliser uniquement réponse API |
| `dashboard/src/App.jsx` | 490 | type device | `'IO'` | mapping local | type générique inventé | afficher type backend ou `—` |
| `dashboard/src/App.jsx` | 491 | label device | id local | mapping local | mapping non confirmé par registre | utiliser nom backend/registre |

Recherche ciblée: aucun `Math.random()` dans `dashboard/src/App.jsx`; aucune alerte ou compteur de menace généré aléatoirement côté dashboard. Les compteurs `stats.attacks` et `stats.total_alerts` sont issus de `/statistics`, mais leurs valeurs initiales sont frontend à zéro. Les données aléatoires restent dans des simulateurs Python hors dashboard.

## 4. ALERT CREATION

### Producteurs directs

| FILE | FUNCTION | TRIGGER | ALERT TYPE | DB TABLE | SIEM EVENT ? | INCIDENT ? | POSSIBLE DUPLICATION ? |
|---|---|---|---|---|---|---|---|
| `backend/mqtt_listener.py:145-147` | `process_message()` drone branch | MQTT type `drone_event` | `drone_<event_type>` | `alerts` | Non via `SmartPortSiem.collect` dans cette branche | Non directement | Oui avec éventuel événement/incident mission ailleurs |
| `backend/mqtt_listener.py:159-164` | `process_message()` IoT branch | chaque tuple dans `decision["alerts"]` | `flood`, `unknown_device`, `bad_token`, `wrong_topic`, `network_flood`, `unknown_ip`, `ml_anomaly` | `alerts` | Oui, un `SiemEventIn` par alerte, `manage_incident=False` | ensuite ActionDispatcher si décision anomalie/red | Oui: alerte directe + SIEM event + ActionDispatcher |
| `backend/services/platform_service.py:49-53` | `PlatformService.ingest_telemetry()` | HTTP/UDP identity evaluation `SiemService.evaluate()` | alertes retournées par `check_security` | `alerts` | Oui, mais événement séparé `telemetry_ingested` lignes 55-57 | `SmartPortSiem.collect` avec défaut `manage_incident=True`, mais `telemetry_ingested` est souvent info | alerte directe + audit SIEM; incident possible si corrélation élevée |
| `backend/siem/managers.py:10-17` | `AlertManager.create()` | `SmartPortSiem.collect()` severity high/critical | `event.event_type` | `alerts` | Oui, événement source dans `siem_events` | `IncidentManager` ensuite si manage_incident | Oui si appelant a déjà créé une Alert directe |
| `backend/main.py:67-73` | `audit_http_requests()` via `SmartPortSiem.collect()` | chaque requête HTTP; severity medium si status >=400 sinon info | normalement aucune Alert pour info/medium sans escalade | `siem_events`, parfois `alerts` | Oui `http_request` | possible seulement après corrélation high/critical | bruit/corrélation avec événements applicatifs |
| `backend/auth.py:68-72` | `_audit_authentication()` | login succès/échec | normalement aucune Alert pour info/medium | `siem_events`, possible Alert après corrélation | Oui `login_success/login_failed` | possible si corrélation | corrélation avec HTTP audit |
| `backend/ros/bridge.py:12-14` | ROS bridge | mission dispatch/fallback | selon `SmartPortSiem.collect`; source `ros2` | `siem_events`, possible `alerts` | Oui `mission_dispatch` | possible high/critical | événement mission + alert drone |
| `backend/main.py:500-508` | `create_incident()` | POST manuel `/incidents` | aucune Alert créée | `incidents` | Non | Incident direct | pas de déduplication |

### Graphe des chemins

```text
MQTT/HTTP/UDP telemetry
  → check_security / check_network_anomalies / legacy ML / advanced ML
  → decision["alerts"]
  → Alert directe dans alerts
  → SmartPortSiem.collect(..., manage_incident=False) pour MQTT
  → SiemEvent dans siem_events
  → ActionDispatcher.handle_detection si anomaly ou threat_level=red
  → Incident dédupliqué dans incidents
  → mission éventuelle

HTTP/UDP telemetry
  → SiemService.evaluate
  → Alert directe dans alerts
  → SmartPortSiem.collect(event_type=telemetry_ingested)
  → SIEM correlation
  → AlertManager/IncidentManager possibles selon severity

SIEM API / auth / HTTP audit / ROS2
  → SmartPortSiem.collect
  → SiemEvent
  → CorrelationEngine
  → AlertManager si severity high/critical
  → IncidentManager si severity high/critical
```

### Duplications plausibles uniquement

1. Une détection MQTT cyber/ML est insérée directement dans `alerts`, puis un événement SIEM correspondant est créé. Si la corrélation SIEM l’escalade, `AlertManager` peut insérer une seconde ligne `alerts` pour le même phénomène.
2. Une anomalie MQTT peut créer un incident via `ActionDispatcher`, tandis qu’un autre chemin `SmartPortSiem.collect(... manage_incident=True)` peut créer un incident pour le même `(device_id,event_type)` si l’événement est collecté avec gestion d’incident.
3. Un même message peut produire simultanément `flood` et `network_flood`: fenêtres et seuils différents (`security.engine` 5 s / >10 messages; `network_monitor` 10 s / >20 paquets), sans clé d’événement commune.
4. Plusieurs prédictions avancées anormales produisent plusieurs `ml_anomaly` pour une seule télémétrie, puis une même détection est traitée par `ActionDispatcher`.
5. Les événements `drone_event` créent une `Alert` info mais ne suivent pas le même chemin SIEM que les alertes IoT; la duplication est donc asymétrique plutôt qu’identique.

## 5. ML

### Chaîne exacte

```text
MQTT IoT payload
  → DeviceGateway.normalize + process_network_data
  → decision_engine.make_decision(data, net_info)
  → sécurité/réseau
  → modèles legacy scalar
  → PredictionService advanced domains
  → legacy network model
  → alert tuples + anomaly_score
  → Alert rows + SIEM event par alerte
  → ActionDispatcher incident/mission
  → WS event telemetry + dashboard counters
```

### Modèles

#### Modèles legacy

- Fichier: `backend/ml/anomaly_detector.py`.
- Bundles: `temperature_model.pkl`, `humidity_model.pkl`, `vibration_model.pkl`, `smoke_model.pkl`, `camera_model.pkl`.
- Appel: `is_anomaly()` depuis `decision_engine.py:41-46`.
- Features: valeur scalaire pour température/humidité/vibration/fumée; `people_count` pour caméra.
- Sortie modèle: prédiction `-1` = anomalie.
- Score: `0.5 - decision_function * 3`, borné `[0,1]`.
- Seuil métier: aucun seuil numérique séparé; la prédiction `-1` décide `ml_anomaly=True`.

#### Modèles avancés actifs au chargement

- Fichier: `backend/ml/prediction_service.py`.
- Bundles `advanced_*.pkl` chargés selon `TRAINING_SPECS`.
- Domains: `temperature`, `humidity`, `battery`, `drone_trajectory`, `sensor_failure`, `flood_attack`, `network_traffic`, `spoofing`, `unknown_device`.
- Features exactes:
  - température/humidité: valeur;
  - batterie: `battery`;
  - trajectoire drone: `x,y,dx,dy,speed`;
  - panne capteur: `gap_seconds,has_measurement`;
  - flood: `packet_count,packet_size`;
  - trafic: `packet_count,bytes_total,avg_interval,throughput`;
  - spoofing: `valid_token,valid_topic`;
  - unknown device: `registered_device`.
- Algorithme attendu: `IsolationForest` entraîné dans `backend/ml/training.py` avec `contamination=0.03` par défaut et `random_state=42`.
- Sortie: `Prediction(domain, anomalous, score, features)`.
- Score runtime: `max(0,min(1,0.5 - decision_function*3))`.
- Seuil métier: pas de seuil numérique additionnel; `model.predict(...) == -1` est le seuil d’anomalie.

#### Modèle réseau legacy

- Fichier: `backend/ml/network_anomaly.py`.
- Bundle: `network_model.pkl`.
- Features: `packet_count`, `bytes_total`, `avg_interval`, `throughput`.
- Sortie: `predict(...) == -1` → `net_ml_anomaly=True`.
- Score dédié: aucun; `decision_engine` force `raw_score` à au moins `0.8` ligne 75.

### Passage anomalie → alerte → SIEM → incident

`backend/decision_engine.py`:

- modèle legacy anormal: ajoute `("ml_anomaly", "Anomalie IA sur <type> (score=<score>)")`, lignes 50-52.
- advanced anormal: ajoute `("ml_anomaly", "AI anomaly: <domain> (score=<score>)")`, lignes 60-64.
- réseau legacy anormal: ajoute `("ml_anomaly", "Anomalie réseau détectée")`, lignes 72-75.
- `threat_level` devient `red` pour les anomalies ML legacy/advanced/réseau.
- `any_anomaly` et `anomaly_score` sont renvoyés.
- `correlate()` (`smart_port/analytics/correlation_engine.py:8-18`) calcule `ai_incident = "ml_anomaly" in kinds or anomaly_score >= 0.8`; cela produit `severity="high"` pour une anomalie IA seule et `critical` si elle coexiste avec une alerte sécurité.
- `mqtt_listener.py:159-164` écrit une Alert et un SiemEvent par alerte; `manage_incident=False` sur cette collecte.
- `mqtt_listener.py:167-172` appelle ensuite `ActionDispatcher` lorsque `decision["anomaly"]` ou `threat_level == "red"`, avec trigger `ml_anomaly` si une alerte ML existe.
- `ActionDispatcher` crée/met à jour un incident, et peut dispatcher une mission si cooldown/mission active l’autorisent.

### ML présenté comme menace sécurité ?

Oui, partiellement et directement:

- techniquement, le type de ligne est `ml_anomaly`, distinct de `bad_token`, `unknown_device`, `network_flood`, etc.;
- opérationnellement, `decision_engine.py` passe `threat_level` à `red` pour toute anomalie ML;
- `correlation_engine.py` classe une anomalie IA seule en `high` via `ai_incident`;
- `ActionDispatcher` reçoit le trigger `ml_anomaly` et peut créer un incident et une mission;
- le dashboard affiche `stats.attacks` sous le libellé “Menaces détectées” (`App.jsx:224`), mais ce compteur backend exclut actuellement `ml_anomaly` et ne compte que `flood`, `unknown_device`, `bad_token`, `wrong_topic`, `network_flood`, `unknown_ip` (`main.py:201-203`);
- `/ml/anomalies` existe mais n’est pas consommé par le dashboard;
- le wording visible des alertes ML est “Anomalie IA sur ...” ou “AI anomaly: ...”; l’UI sécurité présente ces événements dans le “Journal de sécurité” sans catégorie distincte ML/cyber.

## P0: problèmes avant démonstration

- Corriger le contrat WebSocket drone (`event` vs `type`) afin que l’état et les transitions soient réellement visibles.
- Décider et appliquer une authentification WebSocket cohérente avec JWT REST.
- Éviter de présenter `drone_event`/`mission_status` comme une simple activité générique: afficher les transitions mission.
- Supprimer les fallbacks dashboard qui transforment absence de données en état sain, batterie 100 %, santé 100 %, position connue ou inventaire actif.
- Clarifier avant démo qu’une anomalie ML est un signal d’anomalie et non automatiquement une attaque cyber.
- Empêcher ou documenter les doubles créations Alert/SIEM/Incident pour un même phénomène.
- Garantir que les transitions mission DB suivent les transitions mémoire/MQTT dans le scénario de démonstration.

## P1: problèmes importants

- Ajouter reconnexion/backoff WebSocket et stratégie de resynchronisation REST.
- Aligner les endpoints mission utilisés par le dashboard avec l’API versionnée canonique.
- Ajouter une clé d’événement/déduplication commune entre alerte directe, SIEM et incident.
- Distinguer dans l’UI les compteurs “attaques cyber”, “anomalies ML” et “incidents”.
- Traiter séparément les états `completed`/`aborted` reçus par `drone/event` au lieu de créer uniquement une alerte info.
- Remplacer les valeurs génériques “En ligne”, “Opérationnel”, “pending” et “open” quand l’API n’a pas fourni la donnée.

## P2: nettoyage/amélioration

- Retirer les boutons décoratifs sans action (`Vue satellite`, `Voir tout le journal`, notifications).
- Remplacer les libellés hardcodés par le registre backend.
- Documenter les états de compatibilité `sent`/`in_progress` ou les retirer du contrat futur.
- Ajouter une provenance visible (`DB`, `MQTT`, `simulator`, `fallback`) pour les données drone.
- Unifier progressivement les façades root/versionnées après confirmation des consommateurs.

## PROPOSED_MINIMAL_FIX_ORDER

1. Unifier le contrat WS: `event` explicite, payload drone documenté, handler dashboard compatible, sans refactoring général.
2. Corriger l’authentification WS et ajouter une reconnexion/backoff minimale.
3. Désactiver les fallbacks présentés comme états réels: utiliser `unknown/loading` au lieu de 0, 100 %, green et inventaire hardcodé.
4. Séparer les catégories ML/cyber dans la décision, les compteurs et les libellés; conserver les seuils/modèles existants.
5. Dédupliquer le chemin alerte/SIEM/incident et synchroniser les transitions mission DB sur les événements simulator.

MODIFICATIONS_CODE = 0
MODIFICATIONS_DATABASE = 0
