import paho.mqtt.client as mqtt
import json, time, random
from network_config import DEVICES

BROKER = "localhost"
CONFIG = DEVICES["entrepot_E01"]

client = mqtt.Client()
client.connect(BROKER, 1883, 60)

while True:
    # Valeur normale proche de 0, très rare pic
    if random.random() < 0.02:   # 2% de chance d'avoir une valeur anormale
        value = round(random.uniform(10, 50), 1)
    else:
        value = round(random.uniform(0, 1), 1)

    payload = {
        "device_id": "entrepot_E01",
        "type": "smoke",
        "value": value,
        "unit": "ppm",
        "timestamp": time.time(),
        "token": "tk_smoke333",
        "ip_src": CONFIG["ip"],
        "mac_src": CONFIG["mac"],
        "port_src": 1883
    }
    client.publish(CONFIG["topic"], json.dumps(payload))
    print(f"[ENTREPOT E01] {value} ppm")
    time.sleep(10)