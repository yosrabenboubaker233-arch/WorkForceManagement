FROM python:3.10-slim

WORKDIR /app

# Installation des dépendances système nécessaires pour Django/PostgreSQL
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copier et installer les requirements depuis le dossier WorkForce
COPY WorkForce/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copier le reste du code source de l'application Django
COPY WorkForce/ /app/
