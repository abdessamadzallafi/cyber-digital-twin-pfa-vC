import paho.mqtt.client as mqtt
import json, time

client = mqtt.Client()
client.connect("localhost", 1883)
for _ in range(20):
    client.publish("port/container01/temperature", json.dumps({
        "device_id": "temp_01", "type": "temperature", "value": 25, "token": "tk_temp123"
    }))
    time.sleep(0.1)
print("Flood terminé.")