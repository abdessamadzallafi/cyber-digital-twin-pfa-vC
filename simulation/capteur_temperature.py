import paho.mqtt.client as mqtt
import json, time, math
from datetime import datetime
from network_config import DEVICES

BROKER = "localhost"
CONFIG = DEVICES["grue_G01"]

client = mqtt.Client()
client.connect(BROKER, 1883, 60)

while True:
    now = datetime.now()
    hour = now.hour + now.minute/60.0
    # Profil sinusoïdal réaliste : min ~15°C à 4h, max ~35°C à 14h
    base = 25 + 10 * math.sin((hour - 6) * math.pi / 12)
    value = round(base + (0.5 - __import__('random').random()), 1)
    value = max(0, min(50, value))

    payload = {
        "device_id": "grue_G01",
        "type": "temperature",
        "value": value,
        "unit": "°C",
        "timestamp": time.time(),
        "token": "tk_temp123",
        "ip_src": CONFIG["ip"],
        "mac_src": CONFIG["mac"],
        "port_src": 1883
    }
    client.publish(CONFIG["topic"], json.dumps(payload))
    print(f"[GRUE G01] {value}°C")
    time.sleep(5)