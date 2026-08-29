@echo off
echo Lancement des capteurs et du robot...
start "Temperature" cmd /k "venv\Scripts\activate && python simulation\capteur_temperature.py"
start "Humidite" cmd /k "venv\Scripts\activate && python simulation\capteur_humidite.py"
start "Vibration" cmd /k "venv\Scripts\activate && python simulation\capteur_vibration.py"
start "Camera" cmd /k "venv\Scripts\activate && python simulation\camera_sim.py"
start "GPS" cmd /k "venv\Scripts\activate && python simulation\gps_conteneur.py"
start "Barriere" cmd /k "venv\Scripts\activate && python simulation\barriere_sim.py"
start "Fumee" cmd /k "venv\Scripts\activate && python simulation\detecteur_fumee.py"
start "Presence" cmd /k "venv\Scripts\activate && python simulation\detecteur_presence.py"
start "Robot" cmd /k "venv\Scripts\activate && python simulation\robot_sim.py"
echo Toutes les simulations sont lancées.
pause