# SecurIoT-Port
### Simulated IoT Port Supervision, AI Anomaly Detection & Cybersecurity Monitoring

SecurIoT-Port is a software platform prototype for supervising a **simulated port environment**. It combines IoT telemetry collection, machine-learning-based anomaly detection, cybersecurity event monitoring, SIEM correlation, and a web dashboard.

> **Scope and disclaimer:** this project uses simulated devices and generated demonstration data. It is not connected to Tanger Med or any real port infrastructure, and it is not a production-certified industrial security system.

## Project overview

The platform brings together the following capabilities:

- **IoT supervision:** collect and display telemetry from simulated port equipment.
- **MQTT communication:** receive device messages through a Mosquitto broker.
- **AI/ML anomaly detection:** use an Isolation Forest-based pipeline to identify unusual telemetry patterns.
- **Cybersecurity monitoring:** inspect simulated security indicators and suspicious activity.
- **SIEM correlation:** correlate events and support incident/risk visibility.
- **Operational dashboard:** view equipment, alerts, security events, and platform information.
- **Incident reporting:** generate reports from platform events.
- **Simulated response demonstration:** illustrate a response workflow, including simulated inspection missions where enabled.

## Architecture

At a high level, the platform is organized around these components:

```text
Simulated IoT devices
        |
        | MQTT
        v
   Mosquitto broker
        |
        v
   FastAPI backend
   |       |       |
   |       |       +--> Cybersecurity monitoring & SIEM correlation
   |       +----------> ML anomaly detection (Isolation Forest)
   +------------------> Data access, APIs & reporting
        |
        v
   SQLite / JSONL data
        |
        v
   React dashboard
```

The repository contains the backend, dashboard, device/attack simulators, data utilities, and Docker configuration. The implementation is evolving; consult the source and configuration files for the current component boundaries.

## Technology stack

| Area | Technologies |
|---|---|
| Backend API | Python, FastAPI |
| Frontend | React |
| Messaging | MQTT, Eclipse Mosquitto |
| Machine learning | Python, Isolation Forest |
| Security monitoring | SIEM event processing and correlation |
| Persistence | SQLite, JSONL |
| Deployment | Docker, Docker Compose |
| API communication | REST, WebSocket |

## Run locally

### Prerequisites

- Python 3.10+
- Node.js and npm
- Docker Engine and Docker Compose (recommended for the integrated demo)

### Start with Docker Compose

1. Clone the repository and enter its directory:

   ```bash
   git clone https://github.com/abdessamadzallafi/cyber-digital-twin-pfa-vC.git
   cd cyber-digital-twin-pfa-vC
   ```

2. Create the local environment file:

   ```bash
   cp .env.example .env
   ```

3. Review `.env` and replace all example values and secrets. Do not commit this file.

4. Build and start the services:

   ```bash
   docker compose up --build
   ```

5. Open the dashboard and API documentation:

   - Dashboard: http://localhost:3000
   - FastAPI documentation: http://localhost:8000/docs

The Compose configuration is intended for local demonstration and development. Review the broker, authentication, network exposure, secrets, and TLS configuration before any shared or production deployment.

### Run backend and dashboard separately

For manual setup, install the Python dependencies from the repository's dependency files, configure the environment using `.env.example`, and start the backend using the entry point and instructions defined by the current project configuration. Start the React application from the `dashboard/` directory using its npm scripts.

## Testing and validation

Run the test suite from the project root using the project's configured Python environment:

```bash
python -m pytest -q
```

Test results depend on the local environment, installed dependencies, configuration, and available services. No model accuracy, precision, recall, or F1 score is claimed here; those metrics should only be published after a reproducible evaluation on a documented test dataset.

## Security and deployment considerations

This is a development and demonstration prototype. Before exposing it beyond a controlled local environment:

- Enable authenticated MQTT access and TLS.
- Use strong, unique secrets and secure JWT configuration.
- Restrict network exposure and apply least-privilege access.
- Review API authorization, input validation, logging, and error handling.
- Configure persistent storage, backups, and database migration procedures.
- Run dependency, container, and application security checks.
- Validate the anomaly-detection model on representative data and document false-positive/false-negative behavior.

## Current limitations

- Device telemetry and security scenarios are simulated.
- Network threat indicators are based on application-level events; this does not imply live packet capture or a full network IDS.
- ML results depend on the training data and thresholds; formal performance metrics are not stated without a reproducible evaluation.
- Simulated response missions are demonstrations, not control of physical equipment.
- Production deployment requires additional security hardening, operational testing, and infrastructure-specific integration.

## Roadmap

- Stabilize backend, dashboard, MQTT ingestion, and persistence.
- Consolidate database configuration and migration workflows.
- Expand automated regression and integration tests.
- Improve observability, auditability, and security hardening.
- Evaluate anomaly detection with documented datasets and metrics.
- Prepare reproducible deployment and demonstration documentation.

## Project status

SecurIoT-Port is under active stabilization and refinement. Features and setup instructions may evolve as the implementation is consolidated.

## Author

**Abdessamad ZALLAFI**
