import paho.mqtt.client as mqtt
import json
import time
import threading
import os

client = mqtt.Client()
client.connect("localhost", 1883, 60)

BROKER = "localhost"
ROBOT_ID = "robot_01"
TOKEN = os.getenv("SMART_PORT_ROBOT_TOKEN", "")
IP = "192.168.1.100"
MAC = "AA:BB:CC:DD:EE:10"

state = {
    "x": 2, "y": 2, "battery": 100,
    "status": "idle", "mission_id": None
}



def on_message(client, userdata, msg):
    global state
    try:
        data = json.loads(msg.payload.decode())
        if msg.topic == "robot/mission":
            if data.get("robot_id") != ROBOT_ID:
                return
            if data.get("token") != TOKEN:
                print("Mission refusée : mauvais token")
                return
            print(f"Mission reçue: {data}")
            mission_id = data["mission_id"]
            target = data["target"]
            state["status"] = "moving"
            state["mission_id"] = mission_id

            def move():
                while abs(state["x"] - target["x"]) > 1 or abs(state["y"] - target["y"]) > 1:
                    if state["x"] < target["x"]: state["x"] += 1
                    elif state["x"] > target["x"]: state["x"] -= 1
                    if state["y"] < target["y"]: state["y"] += 1
                    elif state["y"] > target["y"]: state["y"] -= 1
                    time.sleep(0.5)
                state["status"] = "inspecting"
                time.sleep(2)
                state["status"] = "idle"
                state["mission_id"] = None
                client.publish("robot/report", json.dumps({
                    "device_id": ROBOT_ID,
                    "type": "robot_report",
                    "ip_src": IP,
                    "mac_src": MAC,
                    "port_src": 1883,
                    "mission_id": mission_id,
                    "result": "OK",
                    "timestamp": time.time()
                }))
            threading.Thread(target=move, daemon=True).start()
    except Exception as e:
        print("Erreur message robot:", e)

client.on_message = on_message
client.subscribe("robot/mission")
client.loop_start()

while True:
    state["timestamp"] = time.time()
    # ✅ Correction : ajout de device_id, type, ip_src, mac_src
    payload = {
        "device_id": ROBOT_ID,
        "type": "robot",
        "token": TOKEN,
        "ip_src": IP,
        "mac_src": MAC,
        "port_src": 1883,
        "x": state["x"],
        "y": state["y"],
        "battery": state["battery"],
        "status": state["status"],
        "mission_id": state["mission_id"],
        "timestamp": state["timestamp"]
    }
    client.publish("robot/status", json.dumps(payload))
    time.sleep(5)
