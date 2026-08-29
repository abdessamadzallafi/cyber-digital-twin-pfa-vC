import paho.mqtt.client as mqtt
import json

client = mqtt.Client()
client.connect("localhost", 1883)
client.publish("port/unknown/device", json.dumps({
    "device_id": "hacker_01", "type": "malware", "value": 0, "token": "bad"
}))
print("Appareil inconnu envoyé.")