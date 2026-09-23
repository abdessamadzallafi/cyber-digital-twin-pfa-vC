# PATCH 3B — ML / SIEM / Alert Semantics + Duplication Fix

Projet : `/home/abdo/Downloads/CyberPort`
Référence : PATCH 3A
Mode : correction du comportement futur uniquement. Aucune donnée historique supprimée ou modifiée.

## 1. Problème identifié

PATCH 3A a confirmé que le chemin MQTT capteur faisait deux écritures d’alerte pour une même détection logique :

```text
make_decision()
  -> mqtt_listener.py:198 : db.add(Alert(...))
  -> mqtt_listener.py:199-202 : SmartPortSiem.collect(...)
       -> SmartPortSiem.collect()
       -> AlertManager.create()
       -> backend/siem/managers.py:14-17 : db.add(Alert(...))
```

Le résultat futur pouvait être :

```text
1 détection logique -> 2 alerts + 1 siem_event
```

Le SIEM event n’était pas la cause de la duplication à supprimer. La seconde alerte provenait de `AlertManager.create()` après l’écriture directe de `mqtt_listener.py`.

PATCH 3A a également montré que `ml_anomaly` passait par `ActionDispatcher.handle_detection()`, qui créait un incident avant de pouvoir déclencher une mission.

## 2. Cause exacte

Fichiers concernés :

- `backend/mqtt_listener.py`
  - ancienne création directe `db.add(Alert(...))` pour chaque élément de `decision["alerts"]`;
  - appel séparé à `SmartPortSiem.collect()` pour le même élément.
- `backend/siem/platform.py`
  - `collect()` crée un `SiemEvent`, puis appelle `AlertManager.create()`.
- `backend/siem/managers.py`
  - `AlertManager.create()` persistait une alerte sans vérifier si un événement logique équivalent avait déjà généré une alerte.
- `backend/services/action_dispatcher.py`
  - `handle_detection()` imposait la création d’un incident, y compris pour `ml_anomaly`.
- `dashboard/src/App.jsx`
  - affichait `stats.attacks` sous le libellé « Menaces détectées », alors que le backend compte des catégories de sécurité/réseau hétérogènes.

## 3. Fichiers modifiés

Modifications PATCH 3B :

- `/home/abdo/Downloads/CyberPort/backend/siem/managers.py`
- `/home/abdo/Downloads/CyberPort/backend/siem/platform.py`
- `/home/abdo/Downloads/CyberPort/backend/services/action_dispatcher.py`
- `/home/abdo/Downloads/CyberPort/backend/mqtt_listener.py`
- `/home/abdo/Downloads/CyberPort/dashboard/src/App.jsx`
- `/home/abdo/Downloads/CyberPort/tests/test_patch3b_semantics.py`
- `/home/abdo/Downloads/CyberPort/PATCH3B_ML_SIEM_FIX.md`

Les autres modifications visibles dans `git status` étaient préexistantes à PATCH 3B et n’ont pas été attribuées à cette phase.

## 4. Ancienne chaîne et nouvelle chaîne

### Ancienne chaîne MQTT

```text
MQTT
 -> make_decision
 -> Alert directe dans mqtt_listener
 -> SmartPortSiem.collect
      -> SiemEvent
      -> AlertManager.create
           -> seconde Alert
 -> ActionDispatcher
      -> Incident
      -> Mission possible
```

### Nouvelle chaîne MQTT

```text
MQTT
 -> make_decision
 -> SmartPortSiem.collect
      -> 1 SiemEvent
      -> AlertManager.create
           -> au maximum 1 Alert primaire pour la clé fonctionnelle
 -> ActionDispatcher
      -> network/security : Incident + Mission possible
      -> ml_anomaly seule : pas d’incident cyber automatique
                           Mission d’inspection opérationnelle possible
```

Le SIEM est conservé. L’écriture directe concurrente dans `mqtt_listener.py` a été supprimée ; le SIEM devient la source canonique de création de l’alerte pour ce chemin.

## 5. Règle de déduplication des alertes

`AlertManager.functional_dedup_key()` dans `backend/siem/managers.py` construit une clé fonctionnelle SHA-256 tronquée, sans utiliser l’identifiant SQLite.

La clé contient :

```text
source
+ device_id
+ event_type / alert_type
+ fenêtre temporelle de 5 secondes
+ message normalisé (espaces compactés, minuscules)
```

La clé est stockée dans `siem_events.correlation_id`, colonne existante. Aucune migration n’est exécutée et aucune colonne SQLite n’est ajoutée.

Lors de la création d’une alerte :

1. recherche d’un SIEM event antérieur avec la même `correlation_id`;
2. exclusion de l’événement courant par son identifiant ORM uniquement pour la requête technique;
3. recherche d’une alerte du même device et même type dans la fenêtre ±5 secondes;
4. si elle existe, aucune nouvelle alerte primaire n’est créée;
5. le nouvel événement SIEM reste conservé.

L’identifiant SQLite n’est jamais utilisé comme identité fonctionnelle.

Conséquence :

```text
même événement logique
 -> 2 SiemEvents possibles si le producteur republie
 -> 1 Alert primaire maximum
```

Deux contextes différents produisent deux clés différentes et peuvent donc toujours produire deux alertes.

Limite volontaire : la déduplication s’applique au chemin SIEM/AlertManager. Les alertes informatives de lifecycle drone, qui ne passent pas par le SIEM dans le listener, restent des événements opérationnels distincts.

## 6. Sémantique ML

`ml_anomaly` est maintenant traitée comme une anomalie :

```text
BEHAVIORAL / TELEMETRY ANOMALY
```

Elle n’est pas automatiquement une attaque cyber.

Le chemin MQTT est désormais :

```text
ml_anomaly
 -> alerte primaire
 -> SIEM event pour traçabilité
 -> pas d’incident cyber automatique
```

Dans `mqtt_listener.py`, si aucune catégorie sécurité explicite n’est présente, le trigger reste `ml_anomaly` et `ActionDispatcher.handle_detection(..., create_incident=False)` est utilisé.

Le niveau opérationnel de la décision ML n’a pas été supprimé. Le modèle peut continuer à recommander une action d’inspection selon les règles métier existantes.

## 7. Sémantique cyber

Les types explicitement sécurité/réseau restent séparés du ML :

- `network_flood`
- `flood`
- `unknown_ip`
- `bad_token`
- `wrong_topic`
- `unknown_device`

La sélection du trigger MQTT utilise désormais la priorité suivante :

1. présence d’au moins une alerte sécurité/réseau -> `network_attack`;
2. sinon présence d’une anomalie -> `ml_anomaly`.

Ainsi, une télémétrie contenant à la fois une anomalie ML et un signal réseau explicite peut encore être traitée par la chaîne cyber, car l’escalade repose alors sur le signal réseau indépendant et non sur le seul modèle ML.

Aucun type réseau n’est transformé en `ml_anomaly`.

## 8. Missions drone

La mission d’inspection ML n’a pas été supprimée arbitrairement.

Elle reste possible si la règle opérationnelle recommande un dispatch et si les garde-fous existants l’autorisent :

- mission active;
- état du `DroneManager`;
- cooldown;
- disponibilité du simulateur.

La mission est interprétée comme :

```text
inspection / anomaly investigation
```

et non comme :

```text
confirmed cyber attack
```

Pour `ml_anomaly` seule, l’action peut donc retourner un `mission_id` tout en retournant :

```text
incident_id = None
incident_created = False
```

Le drone reste un simulateur externe et pédagogique. Aucune nouvelle mission n’a été envoyée pendant cette correction.

## 9. Incidents

La correction introduit un paramètre optionnel :

```python
handle_detection(..., create_incident=True)
```

- `create_incident=True` reste le comportement par défaut pour les appels existants;
- `create_incident=False` est utilisé pour une anomalie ML seule dans le listener MQTT;
- une mission opérationnelle peut encore être créée sans incident cyber.

La logique existante de déduplication `ActionDispatcher` est conservée pour les événements explicitement escaladés :

- `dedup_key = sha256(device_id + anomaly_type)` tronqué;
- fenêtre de 300 secondes par défaut;
- `first_seen` à la création;
- `last_seen` mis à jour;
- `occurrence_count` incrémenté;
- mission active et cooldown vérifiés.

Aucun incident historique n’a été modifié.

### Limite différée

Il existe toujours plusieurs producteurs d’incidents :

- `ActionDispatcher`;
- `IncidentManager` pour les appels SIEM avec `manage_incident=True`;
- endpoint manuel `/incidents`.

Une unification complète nécessiterait une refonte de contrat et une analyse de compatibilité historique plus large. Elle n’a pas été appliquée dans PATCH 3B.

```text
INCIDENT_DEDUP_REQUIRES_FUTURE_REFACTORING
DEFERRED_FOR_SAFETY
```

## 10. Stats dashboard

Le calcul backend de `stats.attacks` n’a pas été modifié.

Il compte toujours :

```text
flood
unknown_device
bad_token
wrong_topic
network_flood
unknown_ip
```

`ml_anomaly` reste exclue de cette métrique et reste exposée séparément par `ml_anomalies`.

Le libellé dashboard a été remplacé :

```text
Menaces détectées
```

devient :

```text
Événements de sécurité
```

Le sous-libellé est :

```text
Sécurité réseau
```

Aucun nombre n’a été artificiellement réduit ou recalculé.

## 11. Séparation visuelle des catégories

La séparation déjà disponible dans le dashboard est conservée :

- `stats.attacks` : événements de sécurité réseau;
- `stats.ml_anomalies` : anomalies ML séparées côté backend;
- `/incidents` : incidents;
- `/api/v1/siem/events` : événements SIEM.

Aucun nouvel endpoint et aucun gros refactoring frontend n’a été introduit dans PATCH 3B.

## 12. Tableau central

| EVENT TYPE | CLASSIFICATION | ALERT | SIEM | CYBER INCIDENT | DRONE MISSION |
|---|---|---:|---:|---:|---:|
| `ml_anomaly` | Behavioral / telemetry anomaly | Oui, 1 primaire max | Oui | Non automatiquement; corrélation indépendante requise | Inspection opérationnelle possible |
| `network_flood` | Network security event | Oui | Oui | Oui possible via `network_attack` | Possible selon dispatch/cooldown |
| `unknown_ip` | Network/security identity event | Oui | Oui | Oui possible via `network_attack` | Possible selon dispatch/cooldown |
| `bad_token` | Device authentication/security event | Oui | Oui | Oui possible via `network_attack` | Possible selon dispatch/cooldown |
| `wrong_topic` | MQTT authorization event | Oui | Oui | Oui possible via `network_attack` | Possible selon dispatch/cooldown |
| `unknown_device` | Device identity/security event | Oui | Oui | Oui possible via `network_attack` | Possible selon dispatch/cooldown |
| `flood` | MQTT/network security event | Oui | Oui | Oui possible via `network_attack` | Possible selon dispatch/cooldown |

## 13. Tests ajoutés et exécutés

Nouveau fichier : `tests/test_patch3b_semantics.py`.

Tests ajoutés :

1. même événement logique -> une seule alerte primaire;
2. `ml_anomaly` -> pas d’incident cyber automatique, mission d’inspection possible;
3. deux contextes différents -> deux alertes conservées;
4. `network_flood` conserve `source=network` et son type sécurité;
5. lecture SQLite en `mode=ro` et hash inchangé;
6. dashboard n’utilise plus « Menaces détectées ».

Commandes exécutées :

```text
pytest -q tests/test_patch3b_semantics.py tests/test_action_dispatcher.py tests/test_mqtt_listener_event.py tests/test_mqtt_safety.py
32 passed, 1 warning

pytest -q tests/test_http_common_event.py tests/test_stabilisation_e8.py
92 passed, 1 warning

python3 -m compileall -q backend smart_port tests/test_patch3b_semantics.py
COMPILE_OK

npm run build
Compiled successfully.
```

Les warnings proviennent de l’environnement SciPy/NumPy et ne sont pas introduits par PATCH 3B.

`git diff --check` ciblé sur les fichiers PATCH 3B passe.

Le `git diff --check` global signale des espaces de fin préexistants dans :

- `backend/network/network_monitor.py`;
- `dashboard/src/index.css`.

Ces fichiers n’ont pas été nettoyés, conformément au périmètre limité.

## 14. Validation intégrité et historique

Aucune commande de test n’a utilisé les bases de production pour écrire des données. Les tests ORM utilisent `sqlite://` en mémoire. Le test d’intégrité utilise explicitement `mode=ro`.

SHA-256 observés avant/après :

```text
data/digital_twin.db
8d7858a5590ea56ebd432cecbb38ac43f73571f50a94a3e0cf2a69a92efa9cb6

 digital_twin.db
d660f1b5bc6eff393426ca2d9dab255e6004770872d9c9647963cac7b85a7cc1
```

Résultat :

- aucune alerte historique supprimée;
- aucun SIEM event historique supprimé;
- aucun incident historique supprimé;
- aucune mission historique supprimée;
- aucune SQLite modifiée;
- aucun Data Lake modifié;
- aucune migration exécutée;
- aucun service redémarré;
- aucun service démarré pendant la validation.

## 15. Limites restantes

1. Les anciennes lignes restent volontairement avec leur ancienne sémantique et leur ancienne cardinalité.
2. La déduplication future repose sur `correlation_id` existant dans `siem_events`; aucun champ `dedup_key` n’a été ajouté à `alerts` pour éviter une migration.
3. Les incidents SIEM génériques et les incidents manuels conservent leurs chemins existants.
4. Le backend expose encore plusieurs métriques historiques (`attacks`, `anomalies`, `risk`) avec des ensembles de types différents; seul le libellé ambigu du dashboard a été corrigé.
5. Aucun nouvel endpoint de séparation ML/SIEM/incident n’a été créé.
6. La mission ML reste une inspection opérationnelle possible, pas une preuve cyber.

```text
DEFERRED_FOR_SAFETY
INCIDENT_DEDUP_REQUIRES_FUTURE_REFACTORING
```

PATCH3B_COMPLETE
DATABASE_MODIFIED = 0
PRODUCTION_DATABASE_MODIFIED = 0