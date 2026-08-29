import paho.mqtt.client as mqtt
import json
import time

BROKER = "localhost"
PORT = 1883

def flood_attack():
    client = mqtt.Client()
    client.connect(BROKER, PORT)
    for _ in range(20):
        client.publish("port/container01/temperature", json.dumps({
            "device_id": "temp_01",
            "type": "temperature",
            "value": 25.0,
            "token": "tk_temp123"
        }))
        time.sleep(0.1)
    client.disconnect()
    print("Flood terminé.")

def spoofing_attack():
    client = mqtt.Client()
    client.connect(BROKER, PORT)
    client.publish("port/container01/temperature", json.dumps({
        "device_id": "temp_01",
        "type": "temperature",
        "value": 999,
        "token": "faux_token"
    }))
    client.disconnect()
    print("Spoofing envoyé.")

def unknown_device_attack():
    client = mqtt.Client()
    client.connect(BROKER, PORT)
    client.publish("port/unknown/device", json.dumps({
        "device_id": "hacker_01",
        "type": "malware",
        "value": 0,
        "token": "bad"
    }))
    client.disconnect()
    print("Appareil inconnu envoyé.")

def freq_anomaly_attack():
    client = mqtt.Client()
    client.connect(BROKER, PORT)
    for _ in range(15):
        client.publish("port/container01/humidity", json.dumps({
            "device_id": "hum_01",
            "type": "humidity",
            "value": 50,
            "token": "tk_hum456"
        }))
        time.sleep(0.3)
    client.disconnect()
    print("Fréquence anormale terminée.")

def impossible_value_attack():
    client = mqtt.Client()
    client.connect(BROKER, PORT)
    client.publish("port/container01/temperature", json.dumps({
        "device_id": "temp_01",
        "type": "temperature",
        "value": -200,
        "token": "tk_temp123"
    }))
    client.disconnect()
    print("Valeur impossible envoyée.")

if __name__ == "__main__":
    print("Lancement des 5 attaques...")
    flood_attack()
    spoofing_attack()
    unknown_device_attack()
    freq_anomaly_attack()
    impossible_value_attack()