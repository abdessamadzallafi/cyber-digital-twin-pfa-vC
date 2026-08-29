FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY backend /app/backend
COPY smart_port /app/smart_port
COPY run.py /app/run.py

EXPOSE 8000
CMD ["python", "run.py"]
