# Architecture de démonstration — Smart Port sécurisé

## Problématique

Un terminal portuaire rassemble des équipements IoT hétérogènes et des flux
critiques. Une panne, une valeur capteur incohérente, un appareil usurpé ou un
flood MQTT peut perturber la manutention et créer un risque de sûreté. La
plateforme fournit une vue opérationnelle temps réel, une preuve horodatée des
événements et une réponse physique par drone autonome.

## Flux logique

```text
Capteurs / équipements IoT simulés
        │ MQTT, HTTP ou UDP
        ▼
Backend FastAPI : normalisation, stockage et analyse applicative
        │
        ├── JSONL Data Lake + SQLite
        ├── règles de sécurité, IDS applicatif et ML
        ▼
SIEM / décision → mission MQTT → drone virtuel MQTT
        │                              │
        └──────────── WebSocket ───────┴──► Dashboard React
```

## Contrat API

Toutes les routes professionnelles sont sous `/api/v1` et protégées par JWT,
sauf la documentation Swagger (`/docs`). Les principaux domaines sont :

| Domaine | Route | Usage |
|---|---|---|
| Équipements | `GET /devices` | inventaire edge |
| Drone | `/drone/status`, `/drone/missions`, `/drone/telemetry` | vol et caméra |
| SIEM | `/siem/events`, `/siem/risk`, `/siem/incidents` | collecte, corrélation, incidents |
| Data Lake | `GET /datalake` | catalogue des flux JSONL |
| Réseau | `GET /network` | métadonnées applicatives simulées ; pas de capture réseau réelle |
| Opérations | `/map`, `/mission`, `/analytics`, `/alerts`, `/reports`, `/statistics` | dashboard |

## Data Lake et IA

Le Data Lake est append-only, en JSONL quotidien : `telemetry/`, `security/`,
`missions/`, `network/`, `logs/`. Chaque ingestion HTTP/UDP/MQTT et chaque
alerte SIEM y laisse une preuve. L’API `GET /api/v1/datalake` fournit le
catalogue consommé par le dashboard; les consommateurs analytiques peuvent
relire les fichiers sans solliciter SQLite. Lancez `python
simulation/data_lake_seed.py` pour générer une démonstration complète.

L’IA combine des modèles entraînés sur données synthétiques avec des règles de
sécurité. Les IP/MAC incluses dans les payloads sont des métadonnées simulées,
pas des observations réseau. `NetworkFlow` est réservé à une future simulation
réseau plus réaliste et n’est pas encore alimenté.
