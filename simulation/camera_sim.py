import paho.mqtt.client as mqtt
import json, time, random
from datetime import datetime
from network_config import DEVICES

BROKER = "localhost"
CONFIG = DEVICES["camera_Q01"]

client = mqtt.Client()
client.connect(BROKER, 1883, 60)

while True:
    hour = datetime.now().hour
    if 6 <= hour < 18:
        base = 5 + int(5 * abs(__import__('math').sin((hour-6)*__import__('math').pi/12)))
    else:
        base = random.randint(0, 2)
    people_count = max(0, base + random.randint(-1, 1))

    # Événement aléatoire (5% de chance)
    event = None
    if random.random() < 0.05:
        event = random.choice(["intrusion", "smoke"])
        confidence = random.uniform(0.85, 0.99)
        print(f"ALERTE CAMÉRA: {event} détecté avec confiance {confidence:.2f}")

    payload = {
        "device_id": "camera_Q01",
        "type": "camera",
        "people_count": people_count,
        "timestamp": time.time(),
        "token": "tk_cam000",
        "ip_src": CONFIG["ip"],
        "mac_src": CONFIG["mac"],
        "port_src": 1883
    }
    if event:
        payload["event"] = event
        payload["confidence"] = confidence

    client.publish(CONFIG["topic"], json.dumps(payload))
    time.sleep(5)