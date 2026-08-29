import uvicorn
from backend.main import app
from smart_port.config import settings

if __name__ == "__main__":
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
