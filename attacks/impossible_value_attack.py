import paho.mqtt.client as mqtt
import json

client = mqtt.Client()
client.connect("localhost", 1883)
client.publish("port/container01/temperature", json.dumps({
    "device_id": "temp_01", "type": "temperature", "value": -200, "token": "tk_temp123"
}))
print("Valeur impossible envoyée.")