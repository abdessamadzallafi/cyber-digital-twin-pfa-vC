import time
from collections import defaultdict
from backend.logger import logger

# Suivi par device_id : fenêtre glissante de 10 secondes
window = 10.0  # secondes
flow_data = defaultdict(lambda: {
    "timestamps": [],
    "sizes": [],
    "ip_src": None,
    "mac_src": None,
    "start_time": None,
    "alert": False
})

def process_network_data(device_id, ip_src, mac_src, packet_size, timestamp=None):
    if timestamp is None:
        timestamp = time.time()
    flow = flow_data[device_id]
    # Nettoyer la fenêtre
    now = time.time()
    cutoff = now - window
    flow["timestamps"] = [t for t in flow["timestamps"] if t > cutoff]
    flow["sizes"] = flow["sizes"][-len(flow["timestamps"]):]  # aligné
    flow["ip_src"] = ip_src
    flow["mac_src"] = mac_src
    flow["start_time"] = min(flow["start_time"] or timestamp, timestamp)

    # Ajouter le paquet actuel
    flow["timestamps"].append(timestamp)
    flow["sizes"].append(packet_size)

    # Calcul des métriques
    packet_count = len(flow["timestamps"])
    bytes_total = sum(flow["sizes"])
    duration = timestamp - flow["timestamps"][0] if packet_count > 1 else 0
    avg_interval = duration / (packet_count - 1) if packet_count > 1 else 0
    throughput = bytes_total / duration if duration > 0 else 0

    network_info = {
        "ip_src": ip_src,
        "mac_src": mac_src,
        "start_time": flow["start_time"],
        "packet_count": packet_count,
        "bytes_total": bytes_total,
        "avg_interval": avg_interval,
        "throughput": throughput,
        "duration": duration
    }
    return network_info

def check_network_anomalies(device_id, net_info):
    """Règles simples IDS réseau"""
    alerts = []
    # Flood si plus de 20 paquets en 10s
    if net_info["packet_count"] > 20:
        alerts.append(("network_flood", f"Flood réseau {device_id}: {net_info['packet_count']} paquets/10s"))
    # IP inconnue (simplifié : vérifier contre une liste autorisée)
    # Ici, on considère que toutes les IP en 192.168.1.x sont autorisées
    if net_info["ip_src"] and not net_info["ip_src"].startswith("192.168.1."):
        alerts.append(("unknown_ip", f"IP inconnue {net_info['ip_src']}"))
    return alerts
