# PATCH 4B — Realtime Robustness / Drone State

Projet : `/home/abdo/Downloads/CyberPort`
Mode : correction ciblée du dashboard uniquement.

## 1. Périmètre appliqué

Corrections limitées aux problèmes démontrés par PATCH 4A :

- cycle de vie WebSocket dashboard ;
- reconnexion contrôlée ;
- traitement d’erreur d’authentification ;
- état explicite `wsStatus` ;
- initialisation drone depuis `/drone/status` ;
- priorité aux télémétries WebSocket récentes ;
- fraîcheur drone `LIVE / STALE / DISCONNECTED / UNKNOWN` ;
- absence de coordonnées ou batterie artificielles.

Aucun changement apporté au backend métier, MQTT, ML, SIEM, alertes, incidents, missions, ORM, migrations, SQLite ou Data Lake.

## 2. Fichiers modifiés

- `dashboard/src/App.jsx`
  - lifecycle WebSocket complet ;
  - reconnexion bornée ;
  - gestion JWT/auth ;
  - état `wsStatus` ;
  - fusion REST/WS drone ;
  - affichage de l’état de connexion et de fraîcheur drone.
- `dashboard/src/realtime.js`
  - fonctions pures de contrat temps réel ;
  - constante de fraîcheur de 10 secondes ;
  - fusion REST/WS ;
  - transitions d’état WebSocket ;
  - politique de reconnexion.
- `dashboard/src/realtime.test.js`
  - tests ciblés PATCH 4B.
- `PATCH4B_REALTIME_FIX.md`
  - présent rapport.

Aucun fichier backend n’a été modifié pour PATCH 4B.

## 3. WebSocket lifecycle

Le dashboard conserve exactement le contrat :

```text
/ws?token=<JWT>
type = "drone_telemetry"
```

Le contrat historique `type = "drone"` n’a pas été réintroduit.

Handlers ajoutés dans `dashboard/src/App.jsx` :

- `onopen` : passe `wsStatus` à `LIVE` et remet le compteur de reconnexion à zéro ;
- `onmessage` : parse le JSON de façon protégée et traite `drone_telemetry` ;
- `onerror` : passe l’état à `DISCONNECTED` ;
- `onclose` : distingue fermeture normale, coupure et code d’authentification `1008` ;
- cleanup : annule le timer, détache les handlers et ferme l’ancien socket.

Le dashboard n’affiche plus un état WebSocket live avant `onopen`.

## 4. Reconnexion contrôlée

La reconnexion est volontairement simple :

- un seul socket actif par effet React ;
- vérification `CONNECTING` / `OPEN` avant de créer un socket ;
- cleanup explicite de l’ancien socket ;
- backoff exponentiel borné : `1s`, `2s`, `4s`, `8s`, `10s` maximum ;
- maximum de 5 tentatives par cycle ;
- timers supprimés dans le cleanup React ;
- aucune reconnexion si l’effet est démonté ;
- aucune reconnexion si `authError` est actif.

Le code `1008` du backend est traité comme une erreur d’authentification :

```text
AUTH_ERROR
Session expirée
```

La reconnexion automatique est arrêtée tant qu’un nouveau token n’est pas disponible.

Une réponse REST `401` active également l’état `AUTH_ERROR` et ferme le socket courant sans lancer de boucle de reconnexion.

## 5. État explicite WebSocket

Valeurs utilisées :

- `CONNECTING`
- `LIVE`
- `DISCONNECTED`
- `AUTH_ERROR`

L’état est visible discrètement dans la barre supérieure :

- `WS CONNECTING`
- `WS LIVE`
- `WS DISCONNECTED`
- `Session expirée`

Le libellé général ne prétend plus que l’ensemble du dashboard est « EN DIRECT » sans information sur le socket.

## 6. Initialisation drone REST

Avant PATCH 4B, `/drone/status` était appelé mais son payload n’était pas fusionné dans `drone`.

Correction :

```text
GET /drone/status
    -> mergeDroneRest()
    -> état drone initial
```

Les champs REST valides pris en compte sont :

- `drone_id` ;
- `mission_id` ;
- `status` ;
- `x`, `y`, `altitude` convertis en `position` uniquement s’ils sont numériques ;
- `battery` uniquement si numérique ;
- `updated_at` conservé comme timestamp REST.

La réponse REST ne définit pas `lastDroneTelemetryAt` et ne suffit donc pas à déclarer le drone `LIVE`.

Une réponse `/drone/status` réussie signifie seulement que l’état REST est disponible, pas que la télémétrie est actuelle.

## 7. Mises à jour drone WebSocket

Seuls les messages avec :

```text
type = "drone_telemetry"
```

sont traités comme télémétrie drone.

Champs consommés :

- `drone_id` ;
- `mission_id` ;
- `status` ;
- `position.x` ;
- `position.y` ;
- `position.altitude` ;
- `battery` ;
- `timestamp`.

Une télémétrie sans timestamp numérique n’actualise pas la fraîcheur live.

Une télémétrie plus ancienne ou égale à la dernière télémétrie connue est ignorée pour éviter un retour arrière.

Les coordonnées et la batterie ne sont jamais fabriquées :

- position absente ou invalide : position précédente conservée, sinon `null` ;
- batterie absente ou invalide : valeur précédente conservée, sinon `null` ;
- timestamp absent ou invalide : pas de nouvelle télémétrie live.

## 8. Priorité REST / WebSocket

Ordre appliqué :

```text
1. drone_telemetry WebSocket récente
2. /drone/status REST
3. UNKNOWN
```

La fusion compare `lastDroneTelemetryAt` et `updated_at` lorsque disponibles.

Une réponse REST plus ancienne ne remplace pas une télémétrie WebSocket plus récente.

Le polling REST à 5 secondes est conservé pour :

- statistics ;
- risk ;
- devices ;
- health ;
- incidents ;
- missions ;
- timeline ;
- drone status ;
- Data Lake.

## 9. Fraîcheur drone

Le seuil backend identifié par PATCH 4A est conservé :

```text
DRONE_STALE_AFTER_SECONDS = 10
```

Le calcul utilise le timestamp réel de la dernière télémétrie WebSocket valide.

| CONDITION | ÉTAT |
|---|---|
| aucune télémétrie connue, WebSocket non fermé | `UNKNOWN` |
| dernière télémétrie âgée de 10 secondes ou moins | `LIVE` |
| dernière télémétrie âgée de plus de 10 secondes, WebSocket disponible | `STALE` |
| dernière télémétrie âgée de plus de 10 secondes et WebSocket fermé | `DISCONNECTED` |
| aucune télémétrie connue et WebSocket fermé | `DISCONNECTED` |

Important : `/drone/status` seul ne produit jamais `LIVE`.

Le statut `LIVE` dépend d’une télémétrie WS valide et récente.

## 10. Données affichées sans invention

Le dashboard ne remplace pas une position absente par des coordonnées par défaut.

Le dashboard ne remplace pas une batterie absente par `100`.

Les valeurs initiales sont `null` / indisponibles tant qu’une source REST ou WebSocket valide ne les fournit pas.

Le statut de fraîcheur est séparé du statut métier drone (`idle`, `flying`, etc.) afin de ne pas confondre :

- état opérationnel du drone ;
- fraîcheur de la télémétrie ;
- état de connexion WebSocket.

## 11. Tests ciblés

Test initial RED observé avant l’implémentation :

```text
Cannot find module './realtime' from 'src/realtime.test.js'
```

Après implémentation :

```text
PASS src/realtime.test.js
Test Suites: 1 passed, 1 total
Tests:       9 passed, 9 total
```

Scénarios couverts :

1. `CONNECTING -> LIVE` après `onopen` ;
2. fermeture -> `DISCONNECTED` ;
3. erreur d’authentification -> `AUTH_ERROR` ;
4. télémétrie drone met à jour position/batterie/status ;
5. `/drone/status` initialise les champs valides ;
6. télémétrie WS plus récente prioritaire sur REST ;
7. `UNKNOWN`, `LIVE`, `STALE`, `DISCONNECTED` ;
8. timestamp de télémétrie invalide ignoré ;
9. aucune position/batterie inventée ;
10. politique de reconnexion arrêtée après erreur d’authentification, limite d’essais ou cleanup.

Le test de cleanup est représenté par la garde `disposed` de la politique de reconnexion ; aucun environnement de test React DOM supplémentaire n’a été introduit.

## 12. Build et validation

Build dashboard exécuté depuis `dashboard/` :

```text
npm run build
Compiled successfully.
```

Compilation Python exécutée par contrôle de non-régression :

```text
python3 -m compileall -q backend
PYTHON_COMPILE_OK
```

Contrôle whitespace ciblé :

```text
git diff --check -- dashboard/src/App.jsx dashboard/src/realtime.js dashboard/src/realtime.test.js
```

Résultat : aucune erreur.

Aucune suite complète de 273 tests n’a été lancée.

Aucun Docker n’a été démarré.

## 13. Queue WebSocket

La queue backend n’a pas été refactorée et son comportement global n’a pas été modifié.

Le risque identifié en PATCH 4A reste présent : un débordement peut perdre un événement avant sa diffusion.

```text
WEBSOCKET_QUEUE_OVERFLOW_DEFERRED
```

Aucun snapshot, replay ou nouveau protocole WebSocket n’a été ajouté.

## 14. Limites restantes

- La queue backend ne rejoue pas les messages perdus en cas de saturation.
- Il n’existe toujours pas de snapshot WebSocket initial ; `/drone/status` reste la source d’initialisation.
- Les statistiques, incidents, missions, risk et Data Lake restent rafraîchis par polling REST à 5 secondes.
- Il n’existe pas encore d’événement WebSocket dédié pour chaque type d’objet métier.
- La limite de reconnexion est par cycle React/token ; une nouvelle authentification démarre un nouveau cycle.
- Le timestamp doit être numérique et comparable à l’horloge Unix frontend pour produire `LIVE`/`STALE` de façon fiable.

## 15. Intégrité des bases

SHA-256 avant/après PATCH 4B :

```text
8d7858a5590ea56ebd432cecbb38ac43f73571f50a94a3e0cf2a69a92efa9cb6  data/digital_twin.db

d660f1b5bc6eff393426ca2d9dab255e6004770872d9c9647963cac7b85a7cc1  digital_twin.db
```

Les hashes sont identiques avant et après les corrections.

Aucune base SQLite, migration ou donnée historique n’a été modifiée.

PATCH4B_COMPLETE
DATABASE_MODIFIED = 0
PRODUCTION_DATABASE_MODIFIED = 0