# PATCH 1 — WebSocket + Drone/Mission Contract

## 1. Fichiers modifiés

Fichiers touchés pour ce patch :

- `backend/auth.py`
- `backend/main.py`
- `backend/mqtt_listener.py`
- `backend/ros/drone_manager.py`
- `backend/ros/drone_models.py`
- `dashboard/src/App.jsx`
- `tests/test_main_mqtt.py`
- `tests/test_mqtt_listener_event.py`

Le dépôt contenait déjà d’autres modifications non liées à ce patch. Elles ont été conservées et non refactorées.

Aucune base SQLite, migration, fichier Data Lake, logique ML ou logique de création d’alertes n’a été modifiée par Patch 1.

## 2. Changements exacts

### WebSocket / JWT

- Le handler `GET /ws` valide maintenant le JWT existant via `get_current_user()` avant `accept()`.
- Token absent ou invalide : fermeture propre avec code WebSocket `1008` et raison `WebSocket authentication failed`.
- Token valide : connexion acceptée puis ajoutée à `connected_websockets` comme avant.
- Le chemin `/ws` n’est plus déclaré public dans la liste des endpoints REST publics.
- Le dashboard réutilise le JWT déjà stocké après login REST et l’envoie via le query parameter `token` de l’URL WebSocket, méthode compatible avec l’API navigateur `WebSocket` utilisée par le projet.
- Les appels REST et le mécanisme JWT existant ne sont pas remplacés.

### Contrat drone

Le backend et le dashboard utilisent désormais le même type canonique :

```json
{
  "type": "drone_telemetry",
  "mission_id": "...",
  "drone_id": "...",
  "status": "...",
  "position": {
    "x": 0.0,
    "y": 0.0,
    "altitude": 0.0
  },
  "battery": 100.0,
  "timestamp": 0.0
}
```

- `backend/mqtt_listener.py` normalise les télémétries drone dans ce format.
- `type` et `event` valent `drone_telemetry` pour conserver la compatibilité avec les consommateurs existants sans maintenir deux contrats concurrents.
- Les anciennes coordonnées plates ne sont plus utilisées par le handler dashboard pour la mise à jour directe ; le dashboard consomme `position.x`, `position.y` et `position.altitude`.
- Les champs indisponibles restent à `null`.
- Le dashboard ne teste plus `update.type === "drone"` pour la télémétrie.
- Les événements de lifecycle MQTT valides sont relayés vers le dashboard sous le même contrat `drone_telemetry`, avec le statut métier correspondant.

### Lifecycle des missions

- La machine d’état existante de `DroneMissionStatus` est utilisée ; aucun nouvel état métier n’a été introduit.
- Les transitions autorisées sont centralisées dans `backend/ros/drone_models.py` :

```text
created -> active | aborted
active -> inspecting | returning_home | completed | aborted
inspecting -> returning_home | completed | aborted
returning_home -> completed | aborted
completed -> terminal
aborted -> terminal
```

- `flying` reste un état opérationnel de `DroneState.status`, pas un nouvel état de mission persistant.
- Les télémétries utilisent `mission_status` pour faire évoluer la mission persistée ; `status="flying"` ne remplace plus le statut de mission par un état non déclaré.
- `status="idle"` sans `mission_id` peut clôturer la mission active courante en `completed`, selon le comportement existant du simulateur.
- Les événements MQTT `mission_started`, `mission_completed` et `mission_aborted` mettent à jour la ligne `missions` uniquement si la transition est valide.
- Une transition invalide ou concernant une autre mission ne remplace pas l’état backend/DB.
- `DroneManager` applique la même validation à son état mémoire et refuse les transitions MQTT incohérentes.
- Les transitions MQTT valides mettent à jour la DB, l’état mémoire, puis publient le contrat WebSocket drone consommé immédiatement par le dashboard.
- Le simulateur reste une source d’événements d’exécution/telemetry MQTT ; il ne crée pas de deuxième mission backend.

## 3. Nouveau contrat WebSocket

Pour une télémétrie drone, la chaîne est maintenant :

```text
Drone Simulator
  -> MQTT drone/telemetry ou drone/gps ou drone/camera
  -> mqtt_listener
  -> validation/persistance mission si mission_status valide
  -> DroneManager.update_telemetry()
  -> update_queue
  -> /ws authentifié par JWT
  -> dashboard App.jsx
```

Pour un événement métier drone :

```text
Drone Simulator
  -> MQTT drone/event
  -> mqtt_listener
  -> mission_started/completed/aborted
  -> validation transition DB + DroneManager
  -> événement WebSocket type=drone_telemetry
  -> dashboard
```

## 4. State machine réellement utilisée

La persistance canonique reste la table existante `missions`, avec le champ Python `Mission.drone_id` mappé vers la colonne SQLite existante `robot_id`.

- Création : `DroneManager.create_inspection()` persiste `created` puis publie la commande MQTT existante.
- Exécution : les événements/télémétries MQTT font progresser la mission selon la machine ci-dessus.
- Mémoire : `DroneManager.mission` et `DroneManager.state` sont synchronisés uniquement si l’identifiant de mission correspond.
- DB : les transitions valides reçues par MQTT sont persistées avant publication dashboard.
- Dashboard : le handler met immédiatement à jour la position, batterie, statut et mission depuis le contrat canonique ; le polling REST existant reste inchangé.

## 5. Tests exécutés

Tests ciblés uniquement :

```text
PYTHONPATH=. pytest -q \
  tests/test_main_mqtt.py::WebSocketAuthTests \
  tests/test_mqtt_listener_event.py::TestDroneTelemetryCommonEvent \
  tests/test_mqtt_listener_event.py::TestDroneEventCommonEvent \
  tests/test_mqtt_safety.py \
  tests/test_action_dispatcher.py
```

Résultat : `17 passed`.

Couverture ajoutée/modifiée :

- JWT WebSocket valide accepté.
- Token WebSocket absent refusé.
- Token WebSocket invalide refusé.
- Contrat drone `type=drone_telemetry` et structure `position` vérifiés.
- Champs drone indisponibles vérifiés à `null`.
- Transition MQTT `created -> active` persistée et publiée au dashboard.
- Transition invalide `created -> completed` refusée sans modification DB.
- Télémétrie drone exclue du moteur de décision/ML.
- Idempotence ActionDispatcher existante vérifiée.

## 6. Résultats de validation

- Syntaxe Python : `python3 -m compileall -q backend smart_port tests` — OK.
- Build dashboard : `npm run build` depuis `dashboard/` — OK, compilation React réussie.
- Contrôle whitespace/diff : `git diff --check` — OK.
- Vérification ciblée du statut Git : aucune modification de `digital_twin.db`, `data/` ou `data_lake/` constatée.
- Aucune suite complète des 273 tests lancée.
- Un warning SciPy/NumPy préexistant a été affiché pendant pytest ; il n’a pas échoué les tests.

## 7. RISKS_REMAINING

- Le token WebSocket est transmis en query parameter, car l’API navigateur `WebSocket` ne permet pas de définir directement l’en-tête `Authorization`. Il faut éviter de journaliser les URLs de handshake en production.
- Le mécanisme existant de queue WebSocket reste borné : en cas de saturation, les mises à jour peuvent être abandonnées comme avant ; aucun replay/sequence ID n’a été ajouté dans ce patch.
- Le polling dashboard existant reste actif comme mécanisme de rattrapage ; les fallbacks, métriques, ML, SIEM et création d’alertes n’ont pas été modifiés.
- Les transitions de lifecycle sont publiées immédiatement lorsqu’elles proviennent du chemin MQTT existant. La reconnexion/replay WebSocket et une nouvelle architecture de diffusion sont hors périmètre.

PATCH1_COMPLETE
DATABASE_MODIFIED = 0
PRODUCTION_DATABASE_MODIFIED = 0
