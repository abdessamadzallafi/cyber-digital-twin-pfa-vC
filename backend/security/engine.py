from collections import defaultdict
import time
from smart_port.edge.device_registry import DEVICE_REGISTRY, LEGACY_DEVICE_ALIASES
from smart_port.analytics.siem import evaluate_identity

# Appareils connus : token valide et topic autorisé
# Backward-compatible export. The canonical inventory is smart_port.edge.
KNOWN_DEVICES = {
    **{key: {"token": value.token, "topic": value.topic} for key, value in DEVICE_REGISTRY.items()},
    **{key: {"token": value[0], "topic": value[1]} for key, value in LEGACY_DEVICE_ALIASES.items()},
}

message_times = defaultdict(list)
FLOOD_WINDOW = 5       # secondes
FLOOD_THRESHOLD = 10   # messages max dans la fenêtre

def check_security(device_id, token, topic):
    alerts = []
    now = time.time()

    # 1-3. Inventory, credential and topic validation from the edge registry.
    identity_alerts = evaluate_identity(device_id, token, topic)
    alerts.extend(identity_alerts)
    if any(kind == "unknown_device" for kind, _ in identity_alerts):
        return alerts

    # 4. Détection de flood
    times = message_times[device_id]
    times.append(now)
    # Nettoyer les anciens timestamps
    message_times[device_id] = [t for t in times if now - t < FLOOD_WINDOW]
    if len(message_times[device_id]) > FLOOD_THRESHOLD:
        alerts.append(("flood", f"Flood MQTT détecté sur {device_id}"))

    return alerts
