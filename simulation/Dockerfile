# Shared image for simulation microservices (E1 + E2).
# Build: docker build --build-arg SERVICE=gateway -t sim-gateway .
FROM python:3.12-slim

ARG SERVICE=gateway
ENV SERVICE=${SERVICE}
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY common /app/common
COPY ${SERVICE}/app.py /app/app.py

EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
