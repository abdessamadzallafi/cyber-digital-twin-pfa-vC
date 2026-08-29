import paho.mqtt.client as mqtt
import json, time, random
from network_config import DEVICES

BROKER = "localhost"
CONFIG = DEVICES["portique_P01"]

client = mqtt.Client()
client.connect(BROKER, 1883, 60)

while True:
    # Vibration de fond faible, parfois pic simulé (mouvement de conteneur)
    if random.random() < 0.9:
        value = round(random.uniform(0, 0.5), 2)
    else:
        value = round(random.uniform(0.5, 3.0), 2)

    payload = {
        "device_id": "portique_P01",
        "type": "vibration",
        "value": value,
        "unit": "g",
        "timestamp": time.time(),
        "token": "tk_vib789",
        "ip_src": CONFIG["ip"],
        "mac_src": CONFIG["mac"],
        "port_src": 1883
    }
    client.publish(CONFIG["topic"], json.dumps(payload))
    print(f"[PORTIQUE P01] {value}g")
    time.sleep(5)