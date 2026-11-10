FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY WorkForce/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY WorkForce/ /app/
