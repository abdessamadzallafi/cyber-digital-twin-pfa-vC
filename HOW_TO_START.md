# 🚀 How to Start the Smart Port Security Platform

## ❌ INCORRECT Way (causes environment variable error)
```bash
source .env
python3 run.py
```
❌ Error: `RuntimeError: Missing required runtime configuration`

**Why?** The `source .env` command doesn't export variables to subprocesses.

---

## ✅ CORRECT Way #1 - Using launch.sh (RECOMMENDED)
```bash
cd /home/abdo/Downloads/cyber-digital-twin
./launch.sh start
```

**What it does:**
- Loads `.env` with `set -a; source .env; set +a`
- Verifies all required variables
- Shows configuration summary
- Starts the application

**Other launch.sh options:**
```bash
./launch.sh start      # Start with python3 run.py
./launch.sh uvicorn    # Start with uvicorn directly
./launch.sh docker     # Start with docker compose
```

---

## ✅ CORRECT Way #2 - Manual Command (without script)
```bash
cd /home/abdo/Downloads/cyber-digital-twin
set -a; source .env; set +a
python3 run.py
```

**Why `set -a; source .env; set +a`?**
- `set -a` = export all variables automatically
- `source .env` = load the .env file
- `set +a` = disable auto-export after loading

This ensures all variables are available to Python.

---

## ✅ CORRECT Way #3 - With Uvicorn (for development)
```bash
cd /home/abdo/Downloads/cyber-digital-twin
set -a; source .env; set +a
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

**Benefits:**
- Auto-reload on code changes
- Better for development
- More control over server options

---

## ✅ CORRECT Way #4 - With Docker
```bash
cd /home/abdo/Downloads/cyber-digital-twin
docker compose up --build
```

**Note:** Make sure `.env` exists before running Docker.

---

## Expected Output When Starting Successfully

```
INFO:     Started server process [40814]
INFO:     Waiting for application startup.
2026-08-17 15:13:10,674 - INFO - Database tables initialized successfully
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

✅ **SUCCESS!** Your application is running.

---

## Access Your Application

After successful startup, you can access:

### API Documentation
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc
- **OpenAPI JSON:** http://localhost:8000/openapi.json

### Health Endpoints
```bash
# Basic health check
curl http://localhost:8000/health

# Platform health (v1)
curl http://localhost:8000/api/v1/platform/health

# Get devices
curl http://localhost:8000/devices
```

### Web Interface
- **Dashboard:** http://localhost:3000 (requires separate npm start)

---

## Troubleshooting Startup Issues

### Issue 1: "Missing required runtime configuration"
**Solution:**
```bash
# Use the correct environment loading
set -a; source .env; set +a
python3 run.py
```

### Issue 2: "Port 8000 already in use"
**Solution:**
```bash
# Kill existing process
lsof -i :8000
kill -9 <PID>

# Or change port in .env
SMART_PORT_API_PORT=8001
```

### Issue 3: "MQTT connection failed"
**Solution:**
```bash
# Start MQTT broker locally
mosquitto -p 1883

# Or with Docker
docker run -d -p 1883:1883 eclipse-mosquitto
```

Note: MQTT is optional - the app continues without it.

### Issue 4: "Database locked"
**Solution:**
```bash
# Remove old database
rm digital_twin.db

# Restart app - it will recreate tables
set -a; source .env; set +a
python3 run.py
```

### Issue 5: "'CallbackAPIVersion' has no attribute"
**This is just a warning**, not an error. It means:
- Your paho-mqtt version is older
- MQTT functionality may be limited
- The app continues running fine

**To fix (optional):**
```bash
pip install --upgrade paho-mqtt
```

---

## Quick Start Commands Reference

| Goal | Command |
|------|---------|
| 🚀 Start app (easiest) | `./launch.sh start` |
| 🚀 Start app (manual) | `set -a; source .env; set +a && python3 run.py` |
| 🚀 Start with auto-reload | `set -a; source .env; set +a && uvicorn backend.main:app --reload` |
| 🐳 Start with Docker | `docker compose up --build` |
| 📖 View API docs | Open http://localhost:8000/docs |
| 💊 Health check | `curl http://localhost:8000/health` |
| 🧪 Run tests | `./test_setup.sh` |

---

## Full Startup Workflow

```bash
# Step 1: Navigate to project
cd /home/abdo/Downloads/cyber-digital-twin

# Step 2: (Optional) Activate virtual environment
source .venv/bin/activate

# Step 3: Start the application using recommended method
./launch.sh start

# Step 4: In another terminal, test it
curl http://localhost:8000/health | jq .
```

---

## Success Indicators

After starting, check for these signs:
- ✅ No errors in console
- ✅ "Application startup complete" message
- ✅ "Uvicorn running on http://0.0.0.0:8000"
- ✅ Can access http://localhost:8000/health
- ✅ Can view API docs at http://localhost:8000/docs

---

## Production Notes

For production deployment:
1. Change `SMART_PORT_ENV=production` in `.env`
2. Use proper HTTPS certificates
3. Configure PostgreSQL instead of SQLite
4. Enable MQTT authentication and TLS
5. Set strong random secrets for JWT and passwords
6. Use Docker with proper resource limits

---

**Summary:** Always use `./launch.sh start` or `set -a; source .env; set +a` before running the application!
