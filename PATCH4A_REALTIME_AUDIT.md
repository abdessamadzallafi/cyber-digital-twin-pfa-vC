# PATCH 4A — Audit read-only temps réel / Dashboard / WebSocket

Projet : `/home/abdo/Downloads/CyberPort`
Mode : audit statique read-only. Aucun code, SQLite, Data Lake, service ou configuration n’a été modifié.

## Verdict

```text
PATCH4A_AUDIT_COMPLETE
DATABASE_MODIFIED = 0
PRODUCTION_DATABASE_MODIFIED = 0
CODE_MODIFIED = 0
```

Les fichiers modifiés et non suivis visibles au début de l’audit sont préexistants. Les seuls nouveaux artefacts autorisés sont ce rapport et `PATCH4A_REALTIME_AUDIT.json`.

## 1. WebSocket backend

### Endpoint et authentification

- Endpoint : `backend/main.py:167-183`, `@app.websocket("/ws")`.
- Le token est lu dans la query string : `?token=<JWT>` (`169`).
- Le serveur appelle `get_current_user(token)` avant `accept()` (`171-177`).
- Token absent ou invalide : fermeture WebSocket code `1008`, raison `WebSocket authentication failed` (`175`).
- Le middleware HTTP JWT n’est pas le mécanisme d’authentification du WebSocket ; l’endpoint fait sa propre validation.
- L’expiration JWT est vérifiée à l’ouverture par `jwt.decode`, mais aucune revalidation périodique du token n’est visible après connexion.
- Il n’y a pas de refresh-token ni de message WS spécifique `401` après expiration.

### Gestion des clients

- Registre global : `connected_websockets = set()` (`backend/main.py:36`).
- Connexion acceptée puis ajoutée au set (`177-178`).
- La coroutine attend `receive_text()` (`180-181`) ; les messages clients ne sont pas interprétés.
- Déconnexion normale : `WebSocketDisconnect`, puis `connected_websockets.discard(websocket)` (`182-183`).
- Erreur d’envoi dans `broadcast()` : le socket est placé dans `dead`, puis retiré du set (`156-165`).
- Shutdown applicatif : fermeture des sockets avec code `1012`, puis `clear()` (`backend/main.py:128-133`).
- Aucun heartbeat, ping applicatif, timeout d’inactivité ou contrôle de fraîcheur du client n’est implémenté.

### File et pertes possibles

- File globale : `update_queue = asyncio.Queue(maxsize=settings.websocket_queue_size)` (`37`), défaut `1000` selon `smart_port/config.py:73`.
- Producteur MQTT : `backend/mqtt_listener.py:91-98`, `_publish_dashboard()` utilise `put_nowait()`.
- Si la file est pleine, le message est rejeté, `metrics["websocket_dropped"]` est incrémenté et le message n’est jamais rejoué.
- `broadcast()` consomme un message une seule fois puis tente de l’envoyer à tous les clients présents. Il n’existe pas de replay, buffer par client, sequence number ou snapshot initial.
- Un client qui se connecte après un événement ne récupère pas cet événement via WebSocket ; il dépend du prochain polling REST ou d’un événement futur.

### Fréquence

- Les événements WebSocket sont event-driven : aucun timer périodique backend pour les publier.
- La télémétrie drone est publiée à chaque message MQTT drone reçu (`mqtt_listener.py:153-166`).
- La télémétrie capteur normale est publiée à chaque message MQTT traité (`mqtt_listener.py:212-215`).
- Aucun heartbeat WebSocket n’est envoyé en l’absence de télémétrie.

## 2. Contrat exact des événements WebSocket

| EVENT TYPE | PRODUCER | PAYLOAD | DASHBOARD CONSUMER |
|---|---|---|---|
| `drone_telemetry` | `backend/mqtt_listener.py:153-166`, `_process_drone_telemetry()` | `{type:"drone_telemetry", event:"drone_telemetry", mission_id, drone_id, status, position:{x,y,altitude}, battery, timestamp}` | `dashboard/src/App.jsx:136-146`, met à jour `drone` |
| `drone_telemetry` pour lifecycle | `backend/mqtt_listener.py:179-186`, branche `drone_event` après transition valide | Même forme `_drone_dashboard_payload`, avec `status` issu de `mission_started/completed/aborted` | Même consommateur `update.type === 'drone_telemetry'` |
| `telemetry` | `backend/mqtt_listener.py:212-215`, branche capteur normal | `{event:"telemetry", device_id, type:<device type>, status, last_value, alerts:[messages], anomaly_score, network, action, timestamp}` | `dashboard/src/App.jsx:148-150`, fusionne dans `devices[device_id]` et ajoute à `events` |

Constat : dans le code dashboard, le contrat ancien `type === "drone"` n’est plus utilisé. Le seul test de type exact est `update.type === 'drone_telemetry'` (`App.jsx:136`). Les chaînes `type === 'drone'` et `type === "drone"` ne sont pas présentes dans `dashboard/src`.

Attention : les payloads de télémétrie normale utilisent `type` pour le type de capteur (`temperature`, `humidity`, etc.) et `event:"telemetry"` pour l’événement. Les payloads drone utilisent `type` et `event` tous deux égaux à `drone_telemetry`. Cette asymétrie est fonctionnelle mais doit rester documentée.

## 3. WebSocket dashboard

### Création et URL

- `dashboard/src/App.jsx:5-6` :
  - API : `REACT_APP_API_URL || http://localhost:8000`;
  - WS : `REACT_APP_WS_URL || API.replace(/^http/, 'ws') + '/ws'`.
- `App.jsx:130-133` crée le socket uniquement quand `token` est présent.
- Le token est ajouté à la query string, avec `encodeURIComponent`.

### Callbacks présents/absents

| Élément | État observé |
|---|---|
| `onmessage` | Présent (`134-152`) |
| `onopen` | Absent |
| `onerror` | Absent |
| `onclose` | Absent |
| Reconnexion | Absente |
| Backoff | Absent |
| Ping/heartbeat client | Absent |
| Cleanup | Présent : `return () => ws.current?.close()` (`153`) |
| Suppression explicite de l’ancien socket avant création | Non explicite ; dépend du cleanup React |
| Gestion 401/1008 après connexion | Absente |
| Détection d’un token expiré | Absente |

Le cleanup ferme le socket lorsque l’effet React est démonté ou lorsque `token` change. Il n’y a pas de boucle de reconnexion, donc une fermeture réseau ou un code `1008` laisse le dashboard sans flux temps réel jusqu’à un changement de token ou un rechargement.

Risque de sockets/listeners multiples : le cleanup React réduit le risque lors des changements de `token`, mais il n’y a pas de garde explicite contre une reconnexion future, car aucune reconnexion n’est implémentée. Le handler `onmessage` est attaché une seule fois par effet.

### Traitement des messages

- Le JSON reçu est parsé sans `try/catch` (`135`). Un message non JSON peut provoquer une exception dans le callback et n’est pas transformé en état d’erreur UI.
- `drone_telemetry` met à jour `telemetry_received`, `drone_id`, `mission_id`, `status`, `position`, `battery`, `updated_at`.
- Tout message possédant `device_id` est ajouté à `devices` et `events` (`148-150`).
- Le temps affiché dans la liste `events` est `new Date().toLocaleTimeString()` au moment de la réception, pas le `timestamp` producteur (`150`).
- Les champs `alerts`, `action`, `anomaly_score` et `network` du message `telemetry` sont conservés dans `events`/`devices`, mais ne mettent pas directement à jour `stats`, `incidents`, `missions` ou `risk`.

## 4. Polling REST et appels ponctuels

### Polling périodique

`dashboard/src/App.jsx:122-128` lance :

- `refresh()` immédiatement après authentification;
- `setInterval(refresh, 5000)` : polling data toutes les 5 secondes;
- `setInterval(() => setNow(new Date()), 1000)` : horloge UI uniquement, pas un polling backend.

À chaque `refresh()` (`87-88`) :

| ENDPOINT | INTERVAL | DONNÉE | POURQUOI | WEBSOCKET DISPONIBLE ? | NÉCESSAIRE ? |
|---|---:|---|---|---|---|
| `/statistics` | 5 s | statistiques, `total_alerts`, `attacks`, `ml_anomalies` | cartes et notifications | Aucun event WS agrégé | Oui dans l’état actuel |
| `/risk` | 5 s | score/level risque | carte risque | Aucun event WS risque | Oui dans l’état actuel |
| `/devices` | 5 s | inventaire DB enrichi, `online`, `last_value`, `last_update`, health | pages overview/devices | WS fournit seulement les mises à jour reçues | Oui pour snapshot/inventaire |
| `/health/{device_id}` | 5 s, un appel par device renvoyé | `health_score` | colonne santé devices | Aucun event WS health | Oui dans l’état actuel |
| `/incidents` | 5 s | incidents | page incidents + badge navigation | Aucun event WS incident | Oui dans l’état actuel |
| `/missions` | 5 s | missions DB | page missions | Aucun event WS mission persisté | Oui dans l’état actuel |
| `/timeline` | 5 s | timeline alerts/incidents/missions | fallback des événements | Aucun event WS historique | Oui comme snapshot |
| `/drone/status` | 5 s | état runtime drone REST | état drone initial/snapshot | Oui, `drone_telemetry` | Potentiellement utile, mais résultat actuellement ignoré côté dashboard |
| `/api/v1/datalake` | 5 s | résumé streams Data Lake | page Data Lake | Aucun event WS Data Lake | Oui dans l’état actuel |

### Appels ponctuels

- `POST /token` (`App.jsx:160`) : authentification, hors polling.
- `GET /measures/{device_id}?limit=24` (`170`) : historique à l’ouverture d’un équipement.
- `POST /report/{device_id}` (`174`) : génération de rapport, action utilisateur.
- `POST /simulate/*` et `POST /force_mission/*` via `launch()` (`169`) : actions utilisateur suivies d’un `refresh()`.

Aucun appel Axios n’est utilisé. Aucun `setTimeout` n’a été trouvé dans le dashboard.

## 5. Matrice REST versus WebSocket

| DONNÉE | REST | WS | ACTUELLEMENT UTILISÉ | PROBLÈME |
|---|---|---|---|---|
| devices | `/devices`, `/api/v1/devices` | `telemetry` avec `device_id` | REST snapshot + WS overlay | `/devices` contient `online/last_update`, mais l’UI utilise peu ces champs; l’état WS n’a pas de timeout |
| statistics | `/statistics` | Aucun | REST toutes les 5 s | pas de push; latence jusqu’à 5 s |
| alerts | `/alerts`, `/security/events`, `/statistics` | `telemetry.alerts` seulement | stats REST + messages WS dans journal | pas de liste d’alertes WS; alertes historiques non chargées comme liste |
| security events | `/security/events`, `/network/stats` | `telemetry` indirect | journal WS/fallback timeline | types de données mélangés dans `events`; pas de contrat WS dédié |
| incidents | `/incidents` | Aucun | REST toutes les 5 s | un incident créé par MQTT n’est pas poussé directement; dépend du polling |
| missions | `/missions`, `/drone/missions`, `/api/v1/platform/mission` | drone lifecycle sous `drone_telemetry` | REST toutes les 5 s + état drone WS | état lifecycle WS ne remplace pas la liste DB; pas d’événement mission dédié |
| drone | `/drone/status`, `/api/v1/drone/status` | `drone_telemetry` | WS pour l’état visible, REST pour `droneState` | le résultat REST `/drone/status` n’est pas fusionné dans `drone` (`114-118`), donc l’UI peut rester UNKNOWN avant une télémétrie WS |
| health | `/health`, `/health/{device_id}` | Aucun | REST | aucun statut live WS; health score n’est pas un heartbeat |
| timeline | `/timeline` | aucun équivalent historique | REST toutes les 5 s + fallback journal | le flux WS n’est pas persisté côté frontend; reload dépend du REST |
| Data Lake | `/api/v1/datalake` | Aucun | REST toutes les 5 s | polling nécessaire, pas de push |

## 6. Données live et provenance des pages

| DATA | SOURCE | UPDATE METHOD | CURRENT STATUS | RISK |
|---|---|---|---|---|
| devices / inventaire | `/devices` DB + registry backend selon route | REST 5 s; overlay WS `telemetry` | Snapshot + partiellement live | `online` et `last_update` ne déterminent pas directement le statut rendu dans la page Devices |
| alert count | `/statistics.total_alerts` | REST 5 s | Actualisé périodiquement | pas instantané; peut être en retard de 5 s |
| security events journal | WS `telemetry`; fallback `/timeline` | WS event-driven + REST fallback | Live seulement si WS connecté; sinon snapshot timeline | journal local peut devenir stale; temps affiché = réception UI |
| incidents | `/incidents` | REST 5 s | Snapshot périodique | pas d’événement push; retard possible et état conservé jusqu’au prochain refresh |
| missions | `/missions` | REST 5 s | Snapshot périodique | lifecycle mission peut arriver WS mais liste DB attend le polling |
| drone position/status | `drone_telemetry` WS | WS event-driven; REST appelé mais résultat non fusionné | Live après première télémétrie WS | aucune distinction stale/disconnected; pas de timeout |
| drone initial status | `/drone/status` | REST 5 s | `droneState` passe ready, mais payload non copié dans `drone` | statut REST réellement ignoré pour le rendu |
| statistics | `/statistics` | REST 5 s | périodique | jamais « live » au sens push |
| health score | `/health/{device_id}` | REST 5 s par device | périodique | health score est un calcul d’anomalies, pas liveness |
| Data Lake | `/api/v1/datalake` | REST 5 s | snapshot | pas de notification append-only |
| historique équipement | `/measures/{id}` | REST à l’ouverture | cache mémoire jusqu’à fermeture/modal suivant | n’est pas live; timestamp transformé en heure locale sans affichage de date |
| horloge UI | `new Date()` local | timer 1 s | live local uniquement | ne prouve pas la fraîcheur backend |

Le badge UI « EN DIRECT » (`App.jsx:246`) décrit l’interface mais ne dépend d’aucun état `ws_connected`, `last_message_at` ou heartbeat. Il peut rester affiché après une perte de connexion.

## 7. Stale data et timestamps

### Seuils existants

- `backend/main.py:203-205` : `active_threshold = now - 10` pour `/statistics`.
- `backend/main.py:568-572` : `/devices` considère une lecture active si `now - last.timestamp < 10`.
- `backend/main.py:239` : `/dashboard` utilise aussi une fenêtre de 10 s.
- `smart_port/config.py:62` : intervalle drone configuré par `SMART_PORT_DRONE_TELEMETRY_INTERVAL`, défaut `2` secondes.
- Aucun seuil de stale/disconnected drone côté dashboard n’est défini.
- Aucun seuil WebSocket côté backend ou frontend n’est défini.

### Risques observés

1. Le backend connaît un seuil de fraîcheur de 10 s pour certaines réponses REST, mais le dashboard n’affiche pas un état `CONNECTED/LIVE`, `STALE`, `DISCONNECTED`, `UNKNOWN` dérivé de ce seuil.
2. Le dashboard stocke `drone.updated_at` depuis le WS (`145`) mais ne compare jamais `Date.now()` à cette valeur.
3. Le dashboard ne conserve pas `last_message_at` global ni `last_ws_error`.
4. Si la télémétrie drone s’arrête, la dernière position, batterie et status restent en mémoire dans `drone` sans expiration.
5. `telemetry_received` reste `true` indéfiniment après un seul message.
6. La page Overview n’affiche le drone que si `telemetry_received && hasPosition(position)` ; après un message ancien, elle peut continuer à afficher l’ancienne position sans signal de vieillissement.
7. Les événements dans la liste reçoivent une heure locale au moment de réception, donc l’UI ne montre pas directement l’âge de la donnée source.
8. `/devices` fournit `online` et `last_update`, mais `Devices` utilise `live.status ?? device.status`; `device.status` n’est pas fourni par `get_all_devices()` (`main.py:592-600`). La valeur `online` n’est pas utilisée pour afficher CONNECTED/STALE.
9. Le statut `health_score` est un ratio d’anomalies ML (`/health/{device_id}`), pas un statut de connectivité.

Le seuil déjà démontré par le backend est donc 10 secondes, mais il ne faut pas l’appeler seuil drone officiel : aucun code dashboard ne l’applique au drone.

## 8. Reconnexion, expiration JWT et cleanup

### Ce qui fonctionne

- Token transmis à la connexion WS.
- Token absent/invalide rejeté côté backend avec code 1008.
- Cleanup React ferme le socket existant quand l’effet est nettoyé.
- Backend retire les sockets morts après `WebSocketDisconnect` ou erreur d’envoi.
- Le shutdown backend ferme les sockets connus.

### Ce qui manque

- Pas de `onopen`, donc aucune confirmation UI de connexion.
- Pas de `onerror`, donc aucune transition d’état visible en erreur.
- Pas de `onclose`, donc aucun déclenchement de reconnexion ni distinction 1008/1000/1012.
- Pas de backoff, jitter ou limite de tentatives.
- Pas de reconnexion après perte réseau.
- Pas de gestion dédiée de JWT expiré.
- Pas de logout automatique sur fermeture code 1008.
- Pas de heartbeat applicatif.
- Pas de snapshot après reconnexion.

Conclusion : le cleanup empêche probablement une accumulation lors d’un changement de token, mais la résilience temps réel n’est pas implémentée.

## 9. Authentification REST et WS

- REST : middleware `jwt_auth_middleware` installé dans `backend/main.py:153`, sauf routes publiques définies dans `backend/auth.py:40-51`.
- Frontend : `authFetch()` ajoute `Authorization: Bearer <token>` (`App.jsx:68-74`).
- Login : `POST /token`, stocke le token dans `localStorage` (`158-164`).
- WS : token dans query string, séparé de l’en-tête REST.
- Le token est conservé dans `localStorage` jusqu’au logout; aucune vérification proactive d’expiration frontend.
- Un token expiré pendant une connexion WS déjà ouverte n’est pas revalidé par le serveur dans le code audité.
- Aucun mécanisme de renouvellement n’est visible.

## 10. Scénarios end-to-end

### Scénario A — MQTT telemetry vers dashboard

```text
MQTT port/#
 -> on_message()
 -> ingress_queue
 -> mqtt_worker()
 -> process_message()
 -> DeviceGateway.normalize()
 -> SensorReading + décision ML/sécurité
 -> _publish_dashboard({event:"telemetry", ...})
 -> update_queue backend
 -> broadcast()
 -> send_json() vers chaque WebSocket
 -> App.jsx onmessage
 -> devices[device_id] + events
 -> affichage Overview/Security
```

Points de retard/perte :

- file d’ingress MQTT pleine : message MQTT rejeté;
- traitement séquentiel du worker : messages en attente;
- `update_queue` WS pleine : message dashboard rejeté, compteur `websocket_dropped`;
- aucun replay pour un client arrivé après l’événement;
- socket fermé : aucun envoi et pas de reconnexion frontend;
- `stats`, `risk`, incidents et missions ne sont pas mis à jour par ce message, mais au prochain polling;
- une exception JSON côté `onmessage` n’est pas gérée par l’UI;
- l’événement peut être visible dans `events` mais ne pas actualiser la carte statistique.

### Scénario B — MQTT anomaly vers alert/SIEM/dashboard

```text
MQTT telemetry
 -> make_decision()
 -> SmartPortSiem.collect()
 -> SiemEvent + AlertManager / incident selon branche
 -> _publish_dashboard({event:"telemetry", alerts, anomaly_score, action})
 -> WebSocket
 -> events/devices frontend
```

Points importants :

- l’alerte/SIEM est persistée avant l’envoi WS dans le worker;
- le frontend reçoit le message d’alerte dans `events`, mais ne recharge pas immédiatement `/alerts`, `/security/events`, `/statistics` ou `/incidents`;
- le compteur et la page incidents peuvent donc rester anciens jusqu’au cycle de 5 s;
- le message WS contient `action`, mais aucune logique frontend spécifique ne l’extrait pour mettre à jour la page Missions/Incidents;
- le SIEM event n’est pas lui-même publié en WS comme événement `siem_event`.

## 11. Tests existants identifiés

Aucun test n’a été modifié ni exécuté pendant cet audit.

Tests pertinents trouvés :

- `tests/test_main_mqtt.py:57-80` : acceptation/rejet WebSocket selon token absent, invalide ou valide.
- `tests/test_mqtt_listener_event.py:318-405` : contrats `drone_telemetry`, payload drone, mission lifecycle et publication dashboard mockée.
- `tests/test_mqtt_safety.py:11-19` : la télémétrie drone ne doit pas atteindre `make_decision`.
- `tests/test_event_normalizer.py:321-381` : classification drone telemetry/drone event et timestamps.
- `tests/test_udp_common_event.py:357-405` : classification drone via UDP et contrat de données.
- `tests/test_http_common_event.py` : ingestion HTTP, normalisation et appels de service.
- `tests/test_stabilisation_e8.py` : chemins HTTP/UDP/CommonEvent et contrats de transport.
- `tests/test_final_stabilisation_predict_reports.py` : API AI et endpoints via `TestClient`.
- `tests/test_siem_report_regression.py` : authentification REST et API rapports SIEM.
- `tests/test_drone_simulator.py` : mission simulator, validation et redelivery.

Couverture absente ou incomplète constatée par recherche :

- pas de test frontend du lifecycle `onopen/onerror/onclose`;
- pas de test de reconnexion WebSocket;
- pas de test de JWT expiré après connexion;
- pas de test de heartbeat/absence de télémétrie;
- pas de test de stale/disconnected drone;
- pas de test de saturation/rejeu de `update_queue`;
- pas de test garantissant la mise à jour simultanée REST + WS des cards/incidents/missions.

## 12. Problèmes classés

### HIGH

1. **Pas de reconnexion WebSocket frontend** : une coupure laisse l’interface sans temps réel.
2. **Pas de distinction stale/disconnected drone** : l’ancienne position peut rester affichée indéfiniment.
3. **Badge « EN DIRECT » non lié à l’état réel de connexion** : risque de présenter une UI comme live après perte WS.
4. **REST `/drone/status` ignoré pour l’état rendu** : le polling indique `droneState=ready` mais ne fusionne pas le payload dans `drone`.
5. **Queue WebSocket sans replay ni snapshot** : perte possible lors d’une saturation ou d’une connexion tardive.

### MEDIUM

6. **Incidents/missions/statistics/risk actualisés uniquement toutes les 5 secondes** : ils ne sont pas réellement push temps réel.
7. **Aucun événement WS dédié pour alert, incident, mission ou SIEM** : tout passe éventuellement dans un payload `telemetry` générique ou par polling.
8. **Pas d’état WS visible côté UI** : aucune indication CONNECTING/CONNECTED/STALE/DISCONNECTED.
9. **Parsing JSON WS sans gestion d’erreur**.
10. **`online` et `last_update` REST ne pilotent pas correctement le statut Devices**.
11. **Timestamps source masqués dans le journal** : l’UI utilise l’heure de réception locale.

### LOW

12. L’endpoint WS accepte les messages entrants mais ne les exploite pas; la boucle `receive_text()` sert uniquement à détecter la déconnexion.
13. Le REST et le WS utilisent deux représentations : `event` décrit la nature de l’événement, `type` décrit parfois le type device et parfois l’événement drone.
14. Le client nouvellement connecté ne reçoit aucune vue initiale des événements déjà persistés via WS, seulement via les appels REST indépendants.

## 13. Corrections proposées pour PATCH 4B

Aucune correction n’a été appliquée dans PATCH 4A.

1. Ajouter un état explicite frontend `wsStatus = CONNECTING | CONNECTED | STALE | DISCONNECTED | AUTH_ERROR`.
2. Implémenter `onopen`, `onerror`, `onclose` avec reconnexion bornée, backoff et cleanup explicite de l’ancien socket.
3. Traiter le code `1008` comme une erreur d’authentification : invalider le token local et demander une reconnexion/login.
4. Ajouter un heartbeat ou un mécanisme de dernier message reçu, sans appeler automatiquement une absence de message « disconnected » tant que la politique n’est pas validée.
5. Appliquer le seuil backend existant de 10 secondes uniquement après décision métier explicite, idéalement via un statut calculé à partir de `updated_at`/`timestamp`.
6. Fusionner le résultat REST `/drone/status` dans `drone` au lieu de ne mettre à jour que `droneState`.
7. Exposer des événements WS dédiés ou un contrat snapshot/delta pour `alert`, `incident`, `mission`, `statistics` et `siem_event`, plutôt que de dépendre du polling pour les pages secondaires.
8. Conserver le polling comme fallback/snapshot jusqu’à preuve de couverture WS complète.
9. Ajouter des tests frontend ou tests de contrat pour reconnexion, expiration JWT, stale drone, payload invalide, queue pleine et absence de sockets multiples.
10. Ajouter un identifiant de séquence ou une stratégie de snapshot après reconnexion si la perte d’événements doit être évitée.

## Conclusion

Le contrat `drone_telemetry` est cohérent entre le producteur backend et le consommateur principal dashboard. Le contrat ancien `type === "drone"` n’est plus utilisé dans le dashboard.

La cohérence temps réel n’est toutefois que partielle : le drone et les dernières télémétries peuvent être reçus par WebSocket, tandis que les statistiques, incidents, missions, health et Data Lake dépendent d’un polling de 5 secondes. La reconnexion, la détection de fraîcheur, le heartbeat et la gestion d’expiration JWT ne sont pas implémentés côté frontend.

PATCH4A_AUDIT_COMPLETE
DATABASE_MODIFIED = 0
PRODUCTION_DATABASE_MODIFIED = 0
CODE_MODIFIED = 0