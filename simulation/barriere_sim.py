import paho.mqtt.client as mqtt
import json, time, random
from network_config import DEVICES

BROKER = "localhost"
CONFIG = DEVICES["portail_N01"]

client = mqtt.Client()
client.connect(BROKER, 1883, 60)

while True:
    # Plus de chance d'être fermée la nuit
    hour = time.localtime().tm_hour
    if 6 <= hour < 20:
        status = random.choice(["open", "closed", "closed"])
    else:
        status = random.choice(["closed", "closed", "open"])  # majoritairement fermée

    payload = {
        "device_id": "portail_N01",
        "type": "barrier",
        "status": status,
        "timestamp": time.time(),
        "token": "tk_gate222",
        "ip_src": CONFIG["ip"],
        "mac_src": CONFIG["mac"],
        "port_src": 1883
    }
    client.publish(CONFIG["topic"], json.dumps(payload))
    print(f"[PORTAIL N01] {status}")
    time.sleep(7)