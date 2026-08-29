# simulation/network_config.py
DEVICES = {
    "grue_G01":     {"ip": "192.168.1.10", "mac": "AA:BB:CC:DD:EE:01", "topic": "port/gantry_crane/temperature"},
    "station_H01":  {"ip": "192.168.1.11", "mac": "AA:BB:CC:DD:EE:02", "topic": "port/weather/humidity"},
    "portique_P01": {"ip": "192.168.1.12", "mac": "AA:BB:CC:DD:EE:03", "topic": "port/gantry_crane/vibration"},
    "camera_Q01":   {"ip": "192.168.1.20", "mac": "AA:BB:CC:DD:EE:04", "topic": "port/quay/camera"},
    "camion_C12":   {"ip": "192.168.1.30", "mac": "AA:BB:CC:DD:EE:05", "topic": "port/vehicle/gps"},
    "portail_N01":  {"ip": "192.168.1.40", "mac": "AA:BB:CC:DD:EE:06", "topic": "port/gate/status"},
    "entrepot_E01": {"ip": "192.168.1.50", "mac": "AA:BB:CC:DD:EE:07", "topic": "port/warehouse/smoke"},
    "parking_P01":  {"ip": "192.168.1.60", "mac": "AA:BB:CC:DD:EE:08", "topic": "port/parking/presence"},
}