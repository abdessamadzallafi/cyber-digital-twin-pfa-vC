import paho.mqtt.client as mqtt
import json, time
from network_config import DEVICES

BROKER = "localhost"
CONFIG = DEVICES["camion_C12"]

client = mqtt.Client()
client.connect(BROKER, 1883, 60)

# Position fixe du terminal (légère variation pour le réalisme)
while True:
    lat = 35.767 + __import__('random').uniform(-0.001, 0.001)
    lon = -5.800 + __import__('random').uniform(-0.001, 0.001)

    payload = {
        "device_id": "camion_C12",
        "type": "gps",
        "latitude": round(lat, 5),
        "longitude": round(lon, 5),
        "timestamp": time.time(),
        "token": "tk_gps111",
        "ip_src": CONFIG["ip"],
        "mac_src": CONFIG["mac"],
        "port_src": 1883
    }
    client.publish(CONFIG["topic"], json.dumps(payload))
    print(f"[CAMION C12] {lat}, {lon}")
    time.sleep(10)