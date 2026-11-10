FROM python:3.10-slim

WORKDIR /app

# Installation optimisée et non interactive
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY WorkForce/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY WorkForce/ /app/
