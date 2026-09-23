# PATCH 3A — Audit read-only ML / SIEM / Alert / Incident / Mission

Date de l’audit : 2026-09-19
Projet : `/home/abdo/Downloads/CyberPort`
Mode : lecture seule sur le code et les SQLite. Aucun service démarré, aucun test exécuté, aucune migration, aucun correctif.

## Verdict

```text
PATCH3A_AUDIT_COMPLETE
DATABASE_MODIFIED = 0
PRODUCTION_DATABASE_MODIFIED = 0
CODE_MODIFIED = 0
```

Les modifications et fichiers non suivis visibles avant l’audit ont été conservés tels quels. Les seuls artefacts autorisés par la mission sont ce rapport et `PATCH3A_ML_SIEM_AUDIT.json`.

## 1. Architecture réelle observée

### Chemin MQTT principal

```text
MQTT port/# ou drone/#
  -> backend.mqtt_listener.on_message()
  -> ingress_queue / mqtt_worker()
  -> process_message()
  -> DeviceGateway.normalize()
  -> write_event("telemetry", data)
  ->
     [drone / drone_gps / camera_stream]
       -> _process_drone_telemetry()
       -> sensor_readings + mission lifecycle
       -> dashboard WebSocket (drone_telemetry)
     [drone_event]
       -> mission lifecycle + alerts(drone_*)
       -> dashboard WebSocket si transition valide
     [autres capteurs]
       -> sensor_readings
       -> process_network_data()
       -> make_decision()
          -> sécurité identité/flood
          -> règles réseau
          -> ML legacy scalaire
          -> ML advanced multi-domain
          -> ML legacy réseau
          -> correlate()
       -> pour chaque décision alert:
          -> alerts (écriture directe)
          -> SmartPortSiem.collect() -> siem_events
             -> AlertManager.create() -> seconde écriture potentielle dans alerts
          -> ActionDispatcher.handle_detection()
             -> incidents (création/déduplication)
             -> missions (si dispatch accepté)
       -> dashboard WebSocket (telemetry)
```

### Chemins complémentaires

- HTTP/UDP telemetry : `backend/services/platform_service.py:23-60`, appelé par `backend/api/v1.py:19-21` et `backend/main.py:44-58`. Crée `sensor_readings`, alertes de sécurité directes, puis un événement SIEM `telemetry_ingested` pour HTTP/UDP.
- SIEM API : `backend/api/siem.py:12-14` -> `SmartPortSiem.collect()`.
- Audit HTTP : `backend/main.py:60-77` -> SIEM `http_request` pour chaque requête.
- Authentification : `backend/auth.py:59-74` -> SIEM `login_success` / `login_failed`.
- Mission API : `backend/api/drone.py:33-38` -> `DroneManager.create_inspection()`.
- Mission manuelle : `backend/main.py:403-409` -> `mission_planner.create_mission()` -> `DroneManager.create_inspection()`.
- ROS2 bridge : `backend/ros/bridge.py:9-15` -> SIEM `mission_dispatch`.

## 2. Cartographie des producteurs

| Table / événement | FILE:LINE | FUNCTION | INPUT | OUTPUT | DB table | WebSocket | CALLER |
|---|---|---|---|---|---|---|---|
| `sensor_readings` MQTT | `backend/mqtt_listener.py:189-194` | `process_message` | payload MQTT normalisé, `device_id`, type, valeur, réseau | `SensorReading` | `sensor_readings` | `telemetry` à `211-214` | `mqtt_worker` à `77-88` |
| `sensor_readings` drone | `backend/mqtt_listener.py:153-166` | `_process_drone_telemetry` | telemetry drone | `SensorReading` + état mission | `sensor_readings` | `drone_telemetry` | `process_message:176-178` |
| `sensor_readings` HTTP/UDP | `backend/services/platform_service.py:40-48` | `PlatformService.ingest_telemetry` | `TelemetryIn` | `SensorReading` | `sensor_readings` | aucun direct dans ce service | `/api/v1/telemetry`, UDP |
| Alert directe décision | `backend/mqtt_listener.py:197-198` | `process_message` | `(alert_type,message)` de `make_decision` | `Alert` | `alerts` | liste dans payload `telemetry` | MQTT capteur |
| Alert directe sécurité HTTP/UDP | `backend/services/platform_service.py:49-53` | `ingest_telemetry` | résultat `SiemService.evaluate` | `Alert` | `alerts` | aucun direct | HTTP/UDP |
| Alert drone lifecycle | `backend/mqtt_listener.py:179-184` | `process_message` | `drone_event.event_type` | `Alert(alert_type="drone_...")` | `alerts` | `drone_telemetry` si transition valide | MQTT `drone/event` |
| Alert SIEM secondaire | `backend/siem/managers.py:9-17` | `AlertManager.create` | `SiemEvent`, sévérité corrélée | `Alert` ou `None` | `alerts` | aucun direct | `SmartPortSiem.collect` |
| SIEM event MQTT décision | `backend/mqtt_listener.py:199-202` | `process_message` | chaque alerte de décision | `SiemEventIn` puis `SiemEvent` | `siem_events` | aucun direct | MQTT capteur |
| SIEM event HTTP telemetry | `backend/services/platform_service.py:55-57` | `ingest_telemetry` | type/device HTTP | `telemetry_ingested` | `siem_events` | aucun direct | API v1 |
| SIEM event HTTP access | `backend/main.py:67-72` | `audit_http_requests` | méthode, route, status | `http_request` | `siem_events` | aucun direct | middleware FastAPI |
| SIEM event auth | `backend/auth.py:67-70` | `_audit_authentication` | username, succès/échec | `login_success/login_failed` | `siem_events` | aucun direct | `authenticate_user` |
| Incident corrélé | `backend/services/action_dispatcher.py:28-52` | `create_or_update_incident` | device, trigger, severity, description | incident nouveau ou mis à jour | `incidents` | inclus dans réponse/action MQTT telemetry | `handle_detection:70-73` |
| Incident SIEM | `backend/siem/managers.py:20-36` | `IncidentManager.create_or_update` | SIEM event, sévérité | incident si high/critical | `incidents` | aucun direct | `SmartPortSiem.collect`, quand `manage_incident=True` |
| Incident manuel API | `backend/main.py:504-518` | `create_incident` | query params | `Incident` direct | `incidents` | aucun direct | `POST /incidents` |
| Mission automatique | `backend/services/action_dispatcher.py:77-91` | `handle_detection` | trigger + dispatch recommandé | `DroneManager.create_inspection` | `missions` | MQTT mission via `DroneMQTTInterface` |
| Mission API drone | `backend/api/drone.py:33-38` | `create_drone_mission` | `MissionRequest` | mission autonome | `missions` | MQTT mission | API protégée |
| Mission manuelle | `backend/main.py:403-409` / `backend/mission_planner.py:10-24` | `force_mission` / `create_mission` | device | mission autonome | `missions` | MQTT mission | API protégée |
| Mission DB | `backend/ros/drone_manager.py:40-69` | `create_inspection` | cible, type, priorité | `Mission` + payload MQTT + Data Lake | `missions` | `drone/mission` | ActionDispatcher, APIs |

Note : `backend/database.py` est une ancienne définition ORM dupliquée ; les imports runtime `from backend.database import ...` résolvent le package `backend/database/` qui expose `backend/database/models.py` et exécute aussi `_upgrade_legacy_schema()` à l’import (`backend/database/__init__.py:10-32`). Cela constitue un risque de split-brain ORM, sans modification effectuée ici.

## 3. Chemins ML actifs et historiques

| Modèle / chemin | Fichier / fonction | Features d’entrée | Sortie | Seuil / règle | Alert | SIEM | Incident | Mission |
|---|---|---|---|---|---|---|---|---|
| Legacy scalar Isolation Forest | `backend/ml/anomaly_detector.py:11-83`, appelé `backend/decision_engine.py:34-51` | une valeur scalaire température, humidité, vibration, smoke ou `people_count` camera | `prediction == -1`, score normalisé `0..1` | décision IF `-1`; score `0.5 - decision*3`, borné 0..1 | `ml_anomaly` | oui via boucle MQTT | oui via ActionDispatcher si MQTT | oui pour vibration/smoke/temperature si anomalie |
| Advanced multi-domain Isolation Forest | `backend/ml/training.py:16-47`, runtime `backend/ml/prediction_service.py:29-105` | temperature, humidity, battery, trajectoire drone, sensor failure, flood, spoofing, unknown device, network traffic | `Prediction(domain, anomalous, score, features)` | décision IF `-1`; score normalisé, modèles `advanced_*.pkl`; entraînement contamination 0.03 | `ml_anomaly` pour chaque prediction anormale | oui via boucle MQTT | oui via ActionDispatcher si MQTT | oui si domaine dans `temperature,battery,drone_trajectory,sensor_failure,flood_attack,network_traffic`, ou corrélation |
| Legacy network model | `backend/ml/network_anomaly.py:8-35`, appelé `decision_engine.py:66-75` | packet_count, bytes_total, avg_interval, throughput | `model.predict == -1` | seuil implicite du modèle `network_model.pkl`; score forcé au minimum 0.8 | `ml_anomaly`, score 0.8 | oui via boucle MQTT | oui via ActionDispatcher | oui car `correlation.dispatch_drone` devient vrai pour `ml_anomaly` |
| Deterministic security | `backend/security/engine.py:17-35` | device/token/topic + fréquence MQTT | tuples sécurité | unknown identity; flood si `>10` messages dans 5 s | security alert | oui | via ActionDispatcher seulement si chemin MQTT et trigger dérivé | `correlate` recommande drone pour catégories sécurité seulement si `ml_anomaly` ou smoke; sinon trigger `network_attack` si red |
| Deterministic network IDS | `backend/network/network_monitor.py:53-65` | packet count et IP registry | `network_flood`, `unknown_ip` | flood si `packet_count > 20`; IP différente du registre | oui | oui via boucle MQTT | oui via ActionDispatcher | trigger `network_attack` dans le listener |

Le chargement est effectué au démarrage dans `backend/main.py:99-103`; les modèles sont optionnels et les erreurs de chargement n’empêchent pas le service de continuer.

## 4. Sémantique des alertes

| alert_type trouvé | Source | Signification | ML ? | sécurité ? | SIEM ? | incident ? | mission ? |
|---|---|---|---:|---:|---:|---:|---:|
| `ml_anomaly` | legacy/advanced/network ML | anomalie statistique ou comportementale | oui | non intrinsèquement | oui MQTT | oui MQTT via ActionDispatcher | oui MQTT selon dispatch/cooldown |
| `flood` | `check_security` | fréquence MQTT excessive | non | oui | oui | oui indirectement si escalade listener | possible via trigger `network_attack` |
| `network_flood` | `check_network_anomalies` | plus de 20 paquets dans fenêtre réseau | non, règle; peut aussi coexister avec ML `flood_attack` | oui | oui | oui indirectement | possible |
| `unknown_ip` | network IDS | IP non enregistrée/différente | non | oui | oui | oui indirectement | possible |
| `unknown_device` | registry/security | équipement inconnu | non | oui | oui | oui indirectement | possible |
| `bad_token` | registry/security | credential invalide | non | oui | oui | oui indirectement | possible |
| `wrong_topic` | registry/security | topic non autorisé | non | oui | oui | oui indirectement | possible |
| `drone_mission_started/completed/rejected` | MQTT drone lifecycle | événement opérationnel de mission | non | non | pas via ce listener; alerte directe seulement | non direct | état mission uniquement |
| `login_success/login_failed` | auth | événement d’authentification | non | sécurité/audit | oui | `login_failed` peut devenir incident via SIEM si high/critical, mais auth `medium` ne le fait pas dans `IncidentManager` | non |
| `http_request` | middleware | audit d’accès HTTP | non | audit, pas attaque | oui | normalement non: succès `info`, erreur `medium` | non |
| `telemetry_ingested` | PlatformService | ingestion HTTP | non | non | oui | non, sévérité par défaut info | non |
| `flood` / `network_flood` dans Data Lake seed | `simulation/data_lake_seed.py:19` | donnée de seed, pas preuve d’un runtime actif | non | étiquette de simulation | Data Lake seulement | non déduit | non déduit |

Classification appliquée : une anomalie ML n’est pas classée automatiquement comme cyberattaque. Le code lui donne toutefois une sévérité `high`/`critical` via corrélation, ce qui déclenche l’escalade opérationnelle dans le chemin MQTT.

## 5. ML anomaly vs cyber attack

### Chaîne `ml_anomaly -> alert -> incident -> mission`

1. `decision_engine.py:50-52`, `61-64` ou `72-75` ajoute `("ml_anomaly", ...)` et force `threat_level="red"`.
2. `mqtt_listener.py:197-202` écrit une alerte directe et collecte un `SiemEvent` avec `manage_incident=False`.
3. Le même `SmartPortSiem.collect()` appelle quand même `AlertManager.create()` (`backend/siem/platform.py:33`) et crée donc potentiellement une seconde alerte.
4. `mqtt_listener.py:205-210` choisit `trigger="ml_anomaly"` et appelle `ActionDispatcher.handle_detection()`.
5. `ActionDispatcher.create_or_update_incident()` crée/déduplique l’incident (`device_id + anomaly_type`, fenêtre de 300 s), puis `should_dispatch_drone()` vérifie active mission et cooldown.
6. `DroneManager.create_inspection()` crée la mission dans `missions` et publie sur MQTT (`backend/ros/drone_manager.py:50-67`).

Donc : le code ne dit pas « ML = attaque cyber », mais le chemin MQTT traite une anomalie ML comme un signal de haute priorité et peut créer un incident et une mission drone.

### Chaîne `network_flood -> alert -> incident -> mission`

1. `network_monitor.py:56-57` produit `network_flood` si `packet_count > 20`.
2. `decision_engine.py:25-29` ajoute l’alerte et place le niveau à red.
3. `mqtt_listener.py:197-202` crée l’alerte directe + SIEM `source="network"`, `manage_incident=False`, donc pas d’incident SIEM à cet endroit.
4. `mqtt_listener.py:206` ne trouve pas `ml_anomaly` et passe `trigger="network_attack"`.
5. `ActionDispatcher` crée/déduplique l’incident `network_attack`; mission possible si dispatch recommandé.

Différence sémantique : `network_flood` est une détection réseau déterministe; l’incident est enregistré sous `anomaly_type="network_attack"`, pas `network_flood`. `ml_anomaly` est un signal ML générique, mais l’incident est enregistré sous `anomaly_type="ml_anomaly"`.

## 6. Duplication potentielle et quantification

### Duplication confirmée par le code

Pour chaque alerte de `decision["alerts"]` sur le chemin MQTT non-drone :

- écriture 1 : `db.add(Alert(...))` à `mqtt_listener.py:198`;
- écriture SIEM : `SmartPortSiem.collect()` à `199-202` crée un `SiemEvent`;
- écriture 2 possible : `AlertManager.create()` à `backend/siem/managers.py:14-17`, car le collect reçoit une sévérité high/medium et la corrélation peut retourner high/critical. Avec `manage_incident=False`, l’incident SIEM est désactivé, mais pas l’alerte SIEM.

Les deux SQLite observées confirment le motif pour les types de décision :

| DB | type | alerts | siem_events | ratio observé |
|---|---|---:|---:|---:|
| `data/digital_twin.db` | `ml_anomaly` | 13 614 | 6 807 | 2.00 |
| `data/digital_twin.db` | `unknown_ip` | 2 224 | 1 112 | 2.00 |
| `data/digital_twin.db` | `flood` | 1 004 | 502 | 2.00 |
| `data/digital_twin.db` | `network_flood` | 546 | 273 | 2.00 |
| `digital_twin.db` | `ml_anomaly` | 5 794 | 2 897 | ~2.00 |
| `digital_twin.db` | `unknown_ip` | 758 | 379 | 2.00 |
| `digital_twin.db` | `flood` | 264 | 132 | 2.00 |
| `digital_twin.db` | `network_flood` | 132 | 66 | 2.00 |

Cela établit un chemin `2 alerts + 1 SIEM event` pour ces alertes, sans conclure que tous les autres événements suivent le même ratio.

Autres producteurs concurrents :

1. MQTT listener : alertes directes + collect SIEM.
2. PlatformService HTTP/UDP : alertes directes + collect `telemetry_ingested`.
3. `SmartPortSiem.collect()` : AlertManager, et IncidentManager si `manage_incident=True`.
4. Middleware HTTP : un SIEM par requête.
5. Auth : un SIEM par tentative.
6. Drone event : alerte directe `drone_*`, sans collect SIEM dans ce branchement.
7. API `/incidents` : incident direct sans déduplication.

`common_event` est calculé dans MQTT (`mqtt_listener.py:171`) et PlatformService (`platform_service.py:29`) mais n’est pas consommé par le stockage ou le SIEM dans les chemins lus; c’est un risque de divergence de provenance, pas une écriture supplémentaire observée.

## 7. Incidents

### Création

- `ActionDispatcher.create_or_update_incident()` : incidents automatiques MQTT, avec `first_seen`, `last_seen`, `occurrence_count=1`, `dedup_key`.
- `IncidentManager.create_or_update()` : incidents SIEM quand `manage_incident=True` et sévérité high/critical. Dans le MQTT décisionnel, le collect passe explicitement `manage_incident=False`.
- `backend/main.py:504-518` : création manuelle/API directe, sans déduplication ni `dedup_key` explicite.

### Déduplication ActionDispatcher

```text
dedup_key = sha256(f"{device_id}:{anomaly_type}").hexdigest()[:32]
```

La recherche réelle utilise `device_id`, `anomaly_type`, `status != resolved` et `last_seen >= now - incident_dedup_window_seconds` (`backend/core/config.py:68`, défaut 300 s). Si trouvé : `last_seen=now`, `occurrence_count += 1`, sévérité potentiellement élevée, description remplacée. Sinon : nouveau incident avec `first_seen=last_seen=now`, compteur 1.

Limites observées : `dedup_key` est calculé puis écrit, mais la requête de déduplication ne filtre pas sur ce champ; les chemins SIEM et API ont leurs propres règles. Les créations concurrentes ne sont pas protégées par une contrainte unique sur `dedup_key`.

### Données observées

- `data/digital_twin.db` : 74 incidents; `ml_anomaly` 51, `network_attack` 18, `impossible_values` 4, `login_failed` 1. Maximum `occurrence_count=912`; 5 incidents ont `dedup_key` NULL.
- `digital_twin.db` : 50 incidents; `ml_anomaly` 39, `network_attack` 9, `login_failed` 1, `login_success` 1. Maximum `occurrence_count=380`; 2 incidents ont `dedup_key` NULL.

Les incidents `login_success`, `impossible_values` et les incidents API directs montrent qu’`anomaly_type` est un champ libre et ne constitue pas à lui seul une preuve d’attaque.

## 8. Missions et triggers

| Trigger | Source / condition | Mission | Incident requis | Alert requise | Cooldown / dédup |
|---|---|---:|---:|---:|---|
| `sensor_anomaly` | trigger accepté par `ActionDispatcher`; pas produit par le `make_decision` MQTT lu | oui si appelé avec dispatch true | oui dans `handle_detection` | pas intrinsèque | active mission + mission manager + cooldown |
| `security_incident` | trigger accepté; pas sélectionné directement par le listener lu | oui si appelé | oui | pas intrinsèque | mêmes garde-fous |
| `network_attack` | listener si red/anomalie sans `ml_anomaly`, notamment `network_flood`, `unknown_ip`, sécurité | oui si accepté | oui | généralement oui en amont | active mission + cooldown |
| `ml_anomaly` | listener si une alerte `ml_anomaly` existe | oui si `dispatch_recommended` vrai | oui | oui en amont | active mission + cooldown |
| `drone_anomaly` | trigger accepté; pas sélectionné par le listener lu | oui si appelé | oui | pas intrinsèque | mêmes garde-fous |
| `manual` | `/force_mission/{device_id}` -> `create_mission(...,"manual")` | oui | non par `force_mission` | non | `DroneManager` bloque mission active; pas ActionDispatcher cooldown |

`ActionDispatcher.handle_detection()` crée toujours l’incident avant de vérifier `dispatch_recommended`; il peut donc y avoir incident sans mission (`not_recommended`, `active_mission`, `cooldown`, `dispatch_failed`).

Le drone runtime est séparé : `_process_drone_telemetry()` indique explicitement que la télémétrie drone est état/preuve et n’est pas envoyée au ML dispatch (`mqtt_listener.py:153-154`). Les événements drone mettent à jour la mission et créent des alertes informatives, mais ne déclenchent pas automatiquement une nouvelle mission.

Données missions observées :

- `data/digital_twin.db` : 35, dont 33 `completed`, 2 `created`.
- `digital_twin.db` : 157, dont 150 `aborted`, 7 `completed`.

## 9. Dashboard et sémantique threat

- `stats.attacks` est calculé backend dans `backend/main.py:209-210` avec : `flood`, `unknown_device`, `bad_token`, `wrong_topic`, `network_flood`, `unknown_ip`.
- `ml_anomaly` n’est pas inclus dans `stats.attacks`; il est exposé séparément comme `ml_anomalies` (`211`) et affiché en état jaune dans `/dashboard` (`245-247`).
- Le dashboard affiche pourtant `stats.attacks` comme « Menaces détectées » (`dashboard/src/App.jsx:270`) : ce sont des alertes de sécurité/réseau, pas une preuve que chaque enregistrement est une attaque confirmée.
- `/risk` utilise une autre liste (`flood`, `unknown_device`, `bad_token`, `network_flood`, `unknown_ip`) et exclut `wrong_topic`, ce qui crée une sémantique différente entre attaques statistiques et risque.
- `api/operations.py:63-65` classe `ml_anomaly`, `network_flood`, `unknown_device`, `bad_token` dans un compteur générique `anomalies`; ce compteur mélange ML, réseau et sécurité.
- Les incidents sont affichés comme incidents, les SIEM events comme événements SIEM; le code lu ne montre pas une table unifiée de « threats ».

## 10. Données réelles observées, lecture seule

Les deux fichiers ont été ouverts via URI SQLite `mode=ro`, `PRAGMA integrity_check` = `ok`; aucun `INSERT`, `UPDATE`, `ALTER`, migration ou import applicatif n’a été exécuté.

### Totaux

| Source | sensor_readings | alerts | siem_events | incidents | missions |
|---|---:|---:|---:|---:|---:|
| `data/digital_twin.db` | 29 069 | 47 679 | 111 550 | 74 | 35 |
| `digital_twin.db` | 11 180 | 8 077 | 43 639 | 50 | 157 |

### Alertes (`alerts.alert_type`)

| Type | data DB | racine DB | Source code / interprétation |
|---|---:|---:|---|
| `http_request` | 29 871 | 931 | audit HTTP, pas attaque |
| `ml_anomaly` | 13 614 | 5 794 | ML anomaly, non cyber par nature |
| `unknown_ip` | 2 224 | 758 | network IDS / identité réseau |
| `flood` | 1 004 | 264 | flood MQTT |
| `network_flood` | 546 | 132 | flood réseau déterministe |
| `bad_token` | 148 | 54 | authentification device invalide |
| `login_success` | 104 | 100 | audit auth réussi |
| `wrong_topic` | 70 | 14 | topic MQTT non autorisé |
| `login_failed` | 38 | 15 | audit auth échoué |
| `drone_mission_completed` | 25 | 0 | événement lifecycle drone |
| `drone_mission_started` | 25 | 0 | événement lifecycle drone |
| `unknown_device` | 8 | 12 | équipement inconnu |
| `drone_mission_rejected` | 2 | 3 | rejet de mission |

### SIEM (`siem_events.event_type` et source)

| Type | data DB | racine DB | Interprétation |
|---|---:|---:|---|
| `http_request` | 102 547 | 39 889 | audit HTTP |
| `ml_anomaly` | 6 807 | 2 897 | ML anomaly propagée par MQTT |
| `unknown_ip` | 1 112 | 379 | network IDS |
| `flood` | 502 | 132 | flood MQTT |
| `network_flood` | 273 | 66 | flood réseau |
| `login_success` | 158 | 221 | auth réussie |
| `bad_token` | 74 | 27 | token invalide |
| `login_failed` | 38 | 15 | auth échouée |
| `wrong_topic` | 35 | 7 | topic incorrect |
| `unknown_device` | 4 | 6 | device inconnu |

Sources SIEM : `data/digital_twin.db` = HTTP 102 547, sensor 7 422, network 1 385, auth 196; `digital_twin.db` = HTTP 39 889, sensor 3 069, network 445, auth 236. Aucun `drone`, `ros2`, `mqtt` ou `udp` n’apparaît dans ces deux distributions observées.

### Incidents (`incidents.anomaly_type`)

| Type | data DB | racine DB | Interprétation |
|---|---:|---:|---|
| `ml_anomaly` | 51 | 39 | escalade opérationnelle d’anomalie ML |
| `network_attack` | 18 | 9 | trigger ActionDispatcher pour signal réseau/sécurité |
| `impossible_values` | 4 | 0 | création directe/API ou validation |
| `login_failed` | 1 | 1 | incident auth observé |
| `login_success` | 0 | 1 | incohérence sémantique possible, ne pas reclasser sans provenance |

### Missions

| Type | data DB | racine DB | Interprétation |
|---|---:|---:|---|
| `completed` | 33 | 7 | lifecycle drone terminé |
| `created` | 2 | 0 | mission créée/pas encore avancée |
| `aborted` | 0 | 150 | mission abandonnée dans cette racine |

### Empreintes de contrôle avant/après écriture du rapport

- `data/digital_twin.db` avant lecture : SHA-256 `8d7858a5590ea56ebd432cecbb38ac43f73571f50a94a3e0cf2a69a92efa9cb6`, taille 43 421 696 octets.
- `digital_twin.db` avant lecture : SHA-256 `d660f1b5bc6eff393426ca2d9dab255e6004770872d9c9647963cac7b85a7cc1`, taille 15 392 768 octets.
- Les connexions ont été fermées en mode read-only; aucune vérification applicative n’a importé `backend.database` afin d’éviter les effets de bord de `create_all` / `_upgrade_legacy_schema`.

## 11. Risques identifiés

1. **HIGH — double écriture d’alertes MQTT** : alerte directe + `AlertManager.create()` pour un même événement SIEM.
2. **HIGH — ML anomaly opérationnellement traité comme signal critique** : `threat_level=red`, incident et mission possibles, alors que la sémantique métier n’est pas une attaque cyber.
3. **HIGH — plusieurs producteurs d’incidents** : ActionDispatcher, IncidentManager et endpoint manuel, avec politiques de déduplication différentes.
4. **HIGH — DB split-brain possible** : défaut runtime `sqlite:///./digital_twin.db` (`smart_port/config.py:29`) et présence d’un second `data/digital_twin.db` avec distributions très différentes.
5. **MEDIUM — dashboard threat semantics** : `stats.attacks` est un agrégat de catégories de sécurité/réseau hétérogènes; `/risk` n’utilise pas exactement la même liste.
6. **MEDIUM — compteurs hétérogènes** : SIEM contient massivement `http_request`, tandis que les alertes de succès HTTP ne sont créées que selon la sévérité corrélée.
7. **MEDIUM — modèle legacy network chargé à l’import** contre modèles advanced chargés au lifespan; le chemin actif dépend de la présence/validité des fichiers joblib.
8. **MEDIUM — API `/incidents` crée directement un incident** sans `first_seen`, `dedup_key` ni passage ActionDispatcher.
9. **LOW — événement drone lifecycle** écrit en alerte directe mais ne passe pas par le SIEM dans `mqtt_listener.py:179-187`.
10. **LOW — CommonEvent calculé mais non propagé** dans les chemins inspectés.

## 12. Corrections proposées pour PATCH 3B — conception seulement

Aucune de ces corrections n’a été appliquée pendant PATCH 3A.

1. Définir un producteur canonique par événement : soit le listener écrit l’alerte, soit SIEM/AlertManager l’écrit, mais pas les deux.
2. Séparer explicitement les catégories `ML_ANOMALY`, `SAFETY_ANOMALY`, `NETWORK_SECURITY`, `AUTH_SECURITY`, `DRONE_LIFECYCLE` et `HTTP_AUDIT` sans renommer rétroactivement les données historiques.
3. Décider une politique explicite : une anomalie ML peut-elle créer un incident ? Si oui, avec sévérité et mission distinctes d’une attaque réseau; sinon bloquer l’escalade ML au niveau ActionDispatcher.
4. Unifier la création/déduplication des incidents; faire respecter `dedup_key` par la requête ou par une contrainte adaptée après étude de migration.
5. Centraliser les triggers de mission et documenter `sensor_anomaly`, `security_incident`, `network_attack`, `ml_anomaly`, `drone_anomaly`, `manual` avec des règles différentes.
6. Remplacer le libellé dashboard « Menaces détectées » par une métrique dont la définition est explicitement alignée avec le backend, ou exposer des compteurs séparés.
7. Choisir et documenter la base canonique (`digital_twin.db` ou `data/digital_twin.db`) après comparaison de provenance; ne supprimer ni fusionner aucune donnée sans plan de migration séparé.
8. Ajouter des tests de cardinalité : une télémétrie donnée doit produire le nombre attendu d’alertes, de SIEM events, d’incidents et de missions.
9. Préserver les modèles legacy et advanced; corriger uniquement leur orchestration/étiquetage si la décision PATCH 3B le demande.

---

## Conclusion

Le pipeline réel est fonctionnellement complet, mais il possède deux propriétés importantes pour la suite :

- une anomalie ML n’est pas nommée attaque cyber dans le code, mais elle est automatiquement escaladable vers incident et mission dans le chemin MQTT;
- les alertes de décision MQTT sont effectivement susceptibles d’être dupliquées, avec le motif observé `2 alerts + 1 SIEM event`.

PATCH 3A est terminé en lecture seule. Aucun code, ORM, dashboard, règle métier, Data Lake, fichier SQLite, service ou base de production n’a été modifié.