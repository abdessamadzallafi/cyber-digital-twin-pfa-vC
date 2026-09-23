# PATCH 2 — Dashboard Data Truth

## 1. Valeur initiale

Avant Patch 2, le dashboard pouvait présenter des valeurs non confirmées :

- `8` équipements sur l’écran de login.
- Une liste de 8 équipements via `Object.keys(DEVICE_LABELS)` lorsque `/devices` retournait une liste vide.
- `100` comme batterie initiale du drone.
- `(10,10)` comme position initiale/fallback visuel du drone.
- `100%` comme santé par défaut dans le tableau des équipements.
- `stats.attacks` était bien la source backend pour les menaces ; aucune constante `42` n’a été ajoutée ou conservée.

Les valeurs internes backend nécessaires au moteur n’ont pas été supprimées.

## 2. Source réelle

### Devices

- Source : `GET /devices`.
- Backend : `backend/main.py:562-602`.
- Le backend construit la liste depuis les `device_id` distincts de `sensor_readings`.
- Le dashboard consomme désormais uniquement cette réponse.

### Threats

- Source : `GET /statistics`.
- Dashboard : `dashboard/src/App.jsx:87-96`, `267-271`, `397-406`.
- Backend : `backend/main.py:198-226`.
- `stats.attacks` reste affiché directement après réception de la réponse backend.
- Aucune modification SIEM, ML, alertes ou calcul des threats.

### Drone telemetry

- Source temps réel : WebSocket authentifié Patch 1.
- Dashboard : `dashboard/src/App.jsx:130-154`.
- Contrat utilisé strictement : `update.type === 'drone_telemetry'`.
- Champs consommés : `drone_id`, `mission_id`, `status`, `position`, `battery`, `timestamp`.
- La télémétrie est marquée reçue uniquement à la réception d’un événement `drone_telemetry`.

### Santé équipement

- Source : `GET /health/{device_id}`.
- Appel effectué uniquement pour les device IDs retournés par `GET /devices` : `dashboard/src/App.jsx:98-105`.
- Le dashboard n’utilise plus `100` comme fallback visuel.
- Si le score est absent ou l’appel échoue, l’UI affiche `N/A`/`Indisponible`.

### Santé système

- Le backend expose `GET /health` avec un état qualitatif (`status`, `api`, `database`, `mqtt`) dans `backend/main.py:266-286`.
- Aucun score numérique global n’est fabriqué dans le dashboard.
- Le texte statique `SYSTÈME EN LIGNE` de l’écran de login a été remplacé par `AUTHENTIFICATION REQUISE`.

## 3. Correction

Fichiers modifiés par Patch 2 :

- `/home/abdo/Downloads/CyberPort/dashboard/src/App.jsx`
- `/home/abdo/Downloads/CyberPort/dashboard/src/App.css`

### Devices

- Suppression du fallback `Object.keys(DEVICE_LABELS)` pour la liste d’inventaire.
- Suppression du fallback de la carte opérationnelle basé sur les 8 labels statiques.
- `GET /devices` est maintenant distingué en états :
  - `loading` → `Chargement…`
  - réponse vide → `0 disponibles` et `Aucun équipement disponible.`
  - réponse valide → nombre exact retourné par l’API
  - erreur/indisponibilité → `Indisponible`
- Les positions de carte statiques ne servent plus à créer des équipements ; elles ne sont appliquées qu’aux équipements réellement retournés par l’API et dont une position visuelle existe déjà.

### Threats

- `stats.attacks` est conservé sans transformation métier.
- Absence/erreur API → `Indisponible`.
- Valeur backend `0` → `0`, sans remplacement par une autre valeur.

### Batterie drone

- Suppression de l’état initial affichable `battery: 100`.
- État initial dashboard : `battery: null`, `telemetry_received: false`.
- Avant télémétrie confirmée : affichage `N/A`.
- Après `drone_telemetry` : affichage de la vraie valeur `battery` reçue.
- Une valeur backend interne par défaut peut toujours exister, mais elle n’est pas affichée comme télémétrie confirmée.

### Position drone

- Suppression de la position initiale dashboard `(10,10)`.
- Suppression du fallback visuel `robot.x || 10` / `robot.y || 10`.
- Le pin drone n’est rendu que si un événement `drone_telemetry` contient une position numérique complète.
- Position absente/incomplète → `Position indisponible`.
- Le fallback `(5,5)` de `backend/ros/mission_planner.py` n’a pas été modifié ; il reste limité à la planification d’un waypoint et n’est pas utilisé comme télémétrie UI.

### Santé équipement

- Suppression du fallback dashboard `health_score ?? 100`.
- Score absent → `N/A`.
- Statut absent → `Indisponible` au lieu de `Opérationnel`.
- Zone absente → `N/A` au lieu de `Terminal principal`.

### Loading / empty / error

Les états sont maintenant séparés dans le dashboard :

- `deviceState`: `loading`, `ready`, `error`.
- `statsState`: `loading`, `ready`, `error`.
- `droneState`: `loading`, `ready`, `error`.
- Les données drone gardent en plus `telemetry_received` pour distinguer état API et télémétrie réellement reçue.

## 4. Comportement si donnée absente

| Donnée | Loading | Vide/absente | Erreur/indisponible |
|---|---|---|---|
| Devices | `Chargement…` | `0 disponibles` / `Aucun équipement disponible.` | `Indisponible` |
| Threats/statistiques | `Chargement…` | valeur backend `0` si réellement retournée | `Indisponible` |
| Batterie drone | non affichée comme mesure | `N/A` | `N/A` |
| Position drone | non affichée | `Position indisponible` | `Position indisponible` |
| Santé équipement | attente API | `N/A` si score absent | `N/A` |
| Santé système globale | non affichée comme score | `N/A` si un score était demandé | aucun score inventé |

## 5. Fallbacks backend conservés

Les valeurs suivantes restent possibles en interne pour le fonctionnement du moteur, mais ne sont pas présentées comme données réelles par le dashboard avant télémétrie confirmée :

- `backend/ros/drone_models.py:74-78` : position et batterie initiales de `DroneState`.
- `backend/database/models.py:110-115` : defaults du modèle `Drone`.
- `backend/main.py:298-299` : `health_score=100` lorsqu’aucune lecture n’existe pour un device.
- `backend/ros/mission_planner.py:19` : waypoint de planification `(5.0, 5.0)` pour une cible inconnue.

INTERNAL_DEFAULT_NOT_DISPLAYED_AS_REAL_DATA

## 6. Tests et validation

Tests backend ciblés de non-régression Patch 1 :

```text
PYTHONPATH=. pytest -q \
  tests/test_main_mqtt.py::WebSocketAuthTests \
  tests/test_mqtt_listener_event.py::TestDroneTelemetryCommonEvent \
  tests/test_mqtt_listener_event.py::TestDroneEventCommonEvent
```

Résultat : `12 passed`.

Build dashboard :

```text
npm run build
```

Résultat : compilation React réussie.

Contrôle diff :

```text
git diff --check -- dashboard/src/App.jsx dashboard/src/App.css
```

Résultat : OK.

Recherche explicite dans `dashboard/src` :

- fallback `Object.keys(DEVICE_LABELS)` pour l’inventaire : absent ;
- `battery: 100` dashboard : absent ;
- position initiale `10,10` : absente ;
- fallback position `|| 10` : absent ;
- fallback dashboard `|| 100` / santé globale `100` : absent ;
- constante dashboard `42` : absente ;
- contrat WebSocket `type === 'drone_telemetry'` : présent.

Aucune modification SQLite, migration, ORM, Data Lake, SIEM, ML ou backend n’a été effectuée pour Patch 2.

## 7. Risques restants

- La carte contient encore des coordonnées visuelles statiques pour certains IDs connus ; elles servent uniquement de layout lorsqu’un device réel correspondant est retourné par `/devices`. Les devices réels sans coordonnée cartographique ne sont pas inventés sur la carte.
- Le backend conserve ses defaults internes, documentés ci-dessus ; ils peuvent apparaître dans d’autres consommateurs non concernés par ce dashboard.
- Le dashboard ne dispose pas d’un score numérique global de santé système ; il n’en fabrique pas.
- Les tests React unitaires dédiés n’existent pas dans le projet actuel ; la validation disponible pour cette phase est le build React, la recherche statique ciblée et les tests backend de non-régression.
- Le conteneur dashboard déjà lancé peut servir une image construite antérieurement ; le build local validé concerne le code source courant et nécessite le cycle de déploiement habituel pour être servi par ce conteneur.

PATCH2_COMPLETE
DATABASE_MODIFIED = 0
PRODUCTION_DATABASE_MODIFIED = 0
