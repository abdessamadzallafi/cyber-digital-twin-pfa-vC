# PATCH 3C — Audit runtime Alert/SIEM dedup

Date : 2026-09-20  
Mode : lecture seule. Aucune migration, suppression, écriture DB, changement de dépendance, rebuild ou redémarrage n'a été effectué.

## A. Runtime réellement exécuté

| Élément | Constat |
|---|---|
| Conteneur backend | `cyberport-backend-1` (`e836f162f274`) ; commande `python run.py` ; état `running` |
| Image réellement utilisée | `cyberport-backend`, digest `sha256:fdae107546bf3d306a1ebe4590ccf1b2327ae73d6c929387a113951f37fd099f` |
| Création image | 2026-09-20 12:18 UTC |
| Démarrage conteneur | 2026-09-20 13:20 UTC |
| Mounts backend | seulement `data/ -> /app/data` et `reports/ -> /app/reports` ; aucun bind mount du code |
| Base runtime auditée | `data/digital_twin.db`, ouverte avec SQLite `mode=ro` |

Le diagnostic s'applique donc au code embarqué dans l'image, et non à un fichier source monté depuis l'hôte.

## B. Vérification source vs image Docker

Comparaison octet à octet entre le workspace et `/app` dans le conteneur :

| Module | Résultat |
|---|---|
| `backend/siem/managers.py` | MATCH ; SHA-256 `945b0469...0d3572a` |
| `backend/siem/platform.py` | MATCH ; SHA-256 `5d0d00cf...5b2c51` |
| `backend/mqtt_listener.py` | MATCH ; SHA-256 `d7b07027...ab8457` |
| `backend/services/action_dispatcher.py` | MATCH |
| `backend/network/network_monitor.py` | MATCH |
| `backend/decision_engine.py` | MATCH |
| `backend/events/normalizer.py` | MATCH |

Les marqueurs Patch 3B sont présents dans le runtime : `DEDUP_WINDOW_SECONDS = 5`, `functional_dedup_key`, affectation de `correlation_id`, et appel MQTT à `SmartPortSiem.collect(..., manage_incident=False)`. L'hypothèse « image Docker ancienne, sans Patch 3B » est donc réfutée avec un niveau de certitude élevé.

## C. Tous les producteurs d'Alert

| Producteur | Chemin | Portée |
|---|---|---|
| `AlertManager.create` | appelé par `SmartPortSiem.collect` | producteur canonique des alertes SIEM ; crée une alerte seulement pour sévérité hors `info`/`low` |
| `mqtt_listener.process_message` | `drone_event` -> `db.add(Alert(... severity="info"))` | uniquement lifecycle drone ; ne participe pas au stress sensor |
| `PlatformService.ingest_telemetry` | ajoute directement les alertes issues de `SiemService.evaluate` | ingress HTTP/UDP, pas le chemin MQTT observé |

Il n'existe pas d'autre `add(Alert)` ou insertion SQL directe dans le code applicatif inspecté. L'endpoint manuel `/incidents` ne crée pas d'alerte.

## D. Tous les producteurs de SIEM

Tous passent par `SmartPortSiem.collect`, lequel **persiste toujours** un `SiemEvent` avant d'essayer de créer une `Alert` :

| Producteur | Source / type typique | Portée |
|---|---|---|
| `mqtt_listener.process_message` | `network` pour `network_flood`/`unknown_ip`; `sensor` pour `unknown_device`/`ml_anomaly` | chemin du stress observé |
| `PlatformService.ingest_telemetry` | `http/telemetry_ingested` | HTTP et UDP |
| middleware `audit_http_requests` | `http/http_request` | chaque requête HTTP, y compris les appels d'audit |
| `auth._audit_authentication` | `auth/login_success|login_failed` | authentification |
| `ros.bridge.dispatch_mission` | `ros2/mission_dispatch` | bridge ROS2 |
| `POST /api/v1/siem/events` | payload client | appel SIEM explicite |

Le `EventNormalizer` est une conversion pure dans les chemins inspectés : il ne crée ni `Alert`, ni `SiemEvent`, ni `Incident`.

## E. Chaînes causales observées

### Chaîne MQTT du stress réellement observée

```text
50 MQTT port/container01/temperature
 -> mqtt_listener.process_message
 -> DeviceGateway.normalize + EventNormalizer.normalize (sans persistance de sécurité)
 -> SensorReading
 -> process_network_data
 -> make_decision
 -> une boucle SmartPortSiem.collect() par tuple (alert_type, message)
 -> SiemEvent systématiquement conservé
 -> AlertManager.create() éventuellement
 -> ActionDispatcher(network_attack) -> Incident unique / occurrence_count++
```

`make_decision` cumule volontairement les familles suivantes au lieu de choisir une alerte unique :

1. sécurité d'identité : `unknown_device` ;
2. IDS réseau : `unknown_ip`, puis `network_flood` lorsque `packet_count > 20` ;
3. ML scalaire température ;
4. prédictions ML multi-domaines (temperature, unknown_device, flood_attack, network_traffic) ;
5. ML réseau legacy : `Anomalie réseau détectée`.

Pour ce device non enregistré, `check_security` retourne `unknown_device`; le compteur réseau séparé produit tout de même `unknown_ip` et le flood. Les modèles ML restent aussi exécutés. C'est donc bien une agrégation de producteurs de détection sur le même paquet, pas une republication MQTT unique par erreur.

### Chaîne incident

```text
décision contenant un type sécurité
 -> trigger = network_attack
 -> ActionDispatcher.handle_detection(..., create_incident=True)
 -> create_or_update_incident(device_id, network_attack)
 -> une ligne Incident, occurrence_count incrémenté pour chaque message
```

`SmartPortSiem.collect(..., manage_incident=False)` empêche parallèlement `IncidentManager` de créer un second incident sur ce chemin MQTT. Le résultat observé (1 incident, `occurrence_count=50`) confirme cette séparation.

## F. Analyse des 65 alerts / 422 SIEM events

Deux exécutions indépendantes ont donné le même résultat :

| Device stress | readings | alerts | SIEM events | incidents | occurrence_count |
|---|---:|---:|---:|---:|---:|
| `stress_1789915013` | 50 | 65 | 422 | 1 | 50 |
| `stress_1789915091` | 50 | 65 | 422 | 1 | 50 |

Pour `stress_1789915091`, les 422 événements se répartissent ainsi :

| source | event_type | SIEM events | correlation_id distincts | alerts |
|---|---|---:|---:|---:|
| network | network_flood | 30 | 30 | 30 |
| network | unknown_ip | 50 | 2 | 2 |
| sensor | unknown_device | 50 | 2 | 2 |
| sensor | ml_anomaly | 292 | 31 | 31 |
| **Total** |  | **422** | **65** | **65** |

Le total est exact : `50 unknown_device + 50 unknown_ip + 30 network_flood + 292 ml_anomaly = 422`.

Les 30 `network_flood` commencent à `21 paquets/10s` puis montent jusqu'à `50 paquets/10s`. Leur message contient le compteur courant, donc les 30 messages normalisés sont différents : ce sont 30 contextes Patch 3B distincts, pas des doublons exacts.

Les 50 `unknown_ip` et 50 `unknown_device` ont chacun le même message fonctionnel mais s'étendent sur deux buckets de cinq secondes : deux `correlation_id` et deux alertes par type. Les 292 événements ML contiennent à la fois des messages stables répétés et des scores/domaines variables ; ils forment 31 couples distincts `(bucket de 5 s, message normalisé)`, donc 31 alertes. Les alertes affichent parfois le message de corrélation `Network and sensor anomaly correlated`, mais cette corrélation est calculée **après** la construction de la clé ; elle ne modifie pas l'identité fonctionnelle d'origine.

Conclusion de classification :

- les 422 SIEM events sont des événements volontairement conservés, issus de plusieurs détecteurs par message ;
- à l'intérieur d'une même clé, les répétitions SIEM sont des doublons fonctionnels conservés par conception ;
- les 65 Alert correspondent exactement aux 65 clés fonctionnelles distinctes ; elles ne sont pas des doublons exacts au sens de Patch 3B ;
- si le besoin produit était « une alerte pour tout le burst de 50 paquets », il s'agit d'un besoin plus large que la règle Patch 3B documentée.

## G. Clé Patch 3B et causes racines

La clé réellement exécutée est :

```text
SHA-256 tronqué de :
source | device_id | event_type | floor(occurred_at / 5 s) | message normalisé
```

L'alerte est supprimée seulement lorsqu'un événement SIEM antérieur a la même clé **et** qu'une alerte du même device/type existe dans ±5 secondes. Les SIEM events ne sont pas supprimés.

| Cause | Certitude | Preuve |
|---|---|---|
| Le runtime contient bien Patch 3B | Confirmée | comparaison octet à octet des modules critiques |
| Plusieurs producteurs de détection sont invoqués par chacun des 50 MQTT messages | Confirmée | `make_decision` agrège sécurité, IDS, ML scalaire, ML avancé et ML réseau ; cardinalité DB exacte |
| Les messages dynamiques `network_flood` et les scores ML cassent volontairement l'égalité de la clé | Confirmée | 30 messages flood tous différents ; 31 clés ML |
| La frontière de bucket 5 s produit deux alertes pour les messages constants | Confirmée | 2 clés pour `unknown_ip` et `unknown_device`, fenêtre observée 14:38:11.501901 à 14:38:17.539614 |
| Les SIEM events sont dédupliqués par Patch 3B | Réfutée | Patch 3B dit explicitement « 2 SiemEvents possibles -> 1 Alert primaire » ; `collect` ajoute toujours l'événement |
| Une écriture directe MQTT concurrente d'Alert subsiste pour le stress sensor | Réfutée | branche directe limitée à `drone_event`; MQTT sensor utilise exclusivement `SmartPortSiem.collect` |
| Une image runtime pré-Patch 3B explique les nombres | Réfutée | modules runtime et source identiques |

## H. Correctif minimal recommandé — ne pas appliquer

Le correctif minimal immédiat est de **corriger le critère de validation**, pas le code : pour Patch 3B, vérifier `alerts == distinct(correlation_id)` par stress device et accepter que `siem_events >= alerts`. Le résultat observé, 65 = 65, satisfait précisément cette règle.

Si l'exigence produit devient réellement « une alerte unique par type pendant un burst », elle doit faire l'objet d'un patch séparé et explicitement versionné :

1. définir une clé d'agrégation métier distincte de la clé d'évidence, par exemple source/device/type/domain sans compteur ni score volatil ;
2. conserver les `SiemEvent` bruts pour l'audit ;
3. appliquer cette clé uniquement à `AlertManager` (ou ajouter un rate-limit avant `collect` si le volume SIEM doit aussi baisser) ;
4. décider explicitement si le bucket doit rester à 5 s ou utiliser une fenêtre glissante.

Ne pas supprimer les messages de flood ou les scores par une normalisation implicite : ce serait un changement de sémantique de sécurité, non une correction technique neutre.

## I. Tests nécessaires après un éventuel correctif

1. Même `source/device/type/message/bucket` répété : 2 SIEM, 1 Alert.
2. Même signal de score variable dans 5 s : comportement explicitement choisi (1 Alert si nouvelle politique, 2 sous Patch 3B actuel).
3. Compteurs `network_flood` 21..50 : conservation de 30 SIEM ; nombre d'Alert conforme à la nouvelle politique.
4. Passage de frontière 5 s : test exact de bucket, sans hypothèse ±5 s ambiguë.
5. Burst 50 MQTT : assertions séparées sur readings, SIEM par type/source, alerts, incident unique et `occurrence_count=50`.
6. Régression : lifecycle drone reste informatif et hors SIEM ; HTTP/UDP, endpoint SIEM, auth audit et ROS2 conservent leurs contrats.
7. Exécution intégrée sur image reconstruite seulement après autorisation explicite, sans migration automatique.

## J. Impact potentiel sur historique/database

Cet audit n'a rien modifié. Une future politique d'agrégation ne doit ni supprimer ni réécrire les lignes historiques. Elle modifierait uniquement la cardinalité future des alertes et éventuellement des SIEM events si une déduplication SIEM était choisie. Aucun changement de schéma n'est requis pour corriger le critère de validation ou pour réutiliser `correlation_id`; toute stratégie plus ambitieuse doit évaluer séparément les impacts de reporting et de rétention.

## K. Verdict final

```text
ROOT_CAUSE_CONFIRMED
```

Le constat « runtime Alert/SIEM dedup FAIL » provenait d'une attente de cardinalité incompatible avec la spécification Patch 3B. Patch 3B est effectivement exécuté : il déduplique les Alert par clé fonctionnelle, tout en conservant chaque SiemEvent. Le stress génère volontairement de multiples types/messages/buckets, donc 65 clés et 422 événements. L'incident unique à 50 occurrences confirme que la déduplication d'incident fonctionne aussi.

```text
PATCH3C_AUDIT_COMPLETE
DATABASE_MODIFIED = 0
SCHEMA_MODIFIED = 0
SOURCE_MODIFIED = 0
DOCKER_RUNTIME_MODIFIED = 0
MIGRATION_PERFORMED = 0
```
