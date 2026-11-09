# Utilisation de l'image officielle Python
FROM python:3.10-slim

# Définition du répertoire de travail
WORKDIR /app

# Empêcher Python d'écrire des fichiers .pyc et d'mettre en buffer les logs
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Installation des dépendances système nécessaires pour PostgreSQL et compilation
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copie et installation des dépendances Python
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copie du reste du projet
COPY . /app/

# Exposition du port par défaut de Django
EXPOSE 8000

# Commande pour lancer les migrations et démarrer le serveur de développement (ou Gunicorn en prod)
CMD ["python", "WorkForce/manage.py", "runserver", "0.0.0.0:8000"]