import paho.mqtt.client as mqtt
import json, time, random
from network_config import DEVICES

BROKER = "localhost"
CONFIG = DEVICES["parking_P01"]

client = mqtt.Client()
client.connect(BROKER, 1883, 60)

while True:
    hour = time.localtime().tm_hour
    # Plus de présence en journée
    if 6 <= hour < 18:
        presence = random.choice([True, True, True, False])
    else:
        presence = random.choice([True, False, False, False])

    payload = {
        "device_id": "parking_P01",
        "type": "presence",
        "status": presence,
        "timestamp": time.time(),
        "token": "tk_pres444",
        "ip_src": CONFIG["ip"],
        "mac_src": CONFIG["mac"],
        "port_src": 1883
    }
    client.publish(CONFIG["topic"], json.dumps(payload))
    print(f"[PARKING P01] {'Occupé' if presence else 'Libre'}")
    time.sleep(5)