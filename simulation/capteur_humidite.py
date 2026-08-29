import paho.mqtt.client as mqtt
import json, time, math
from datetime import datetime
from network_config import DEVICES

BROKER = "localhost"
CONFIG = DEVICES["station_H01"]

client = mqtt.Client()
client.connect(BROKER, 1883, 60)

while True:
    hour = datetime.now().hour + datetime.now().minute/60.0
    # Humidité inversement proportionnelle à la température (simplifié)
    base = 50 + 15 * math.sin((hour - 6) * math.pi / 12)   # plus humide la nuit
    value = round(base + (0.5 - __import__('random').random()) * 2, 1)
    value = max(20, min(90, value))

    payload = {
        "device_id": "station_H01",
        "type": "humidity",
        "value": value,
        "unit": "%",
        "timestamp": time.time(),
        "token": "tk_hum456",
        "ip_src": CONFIG["ip"],
        "mac_src": CONFIG["mac"],
        "port_src": 1883
    }
    client.publish(CONFIG["topic"], json.dumps(payload))
    print(f"[STATION H01] {value}%")
    time.sleep(5)