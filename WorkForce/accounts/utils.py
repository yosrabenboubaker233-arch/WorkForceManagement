"""
Utilitaires de création de compte — génération d'un nom d'utilisateur
unique et d'un mot de passe temporaire sécurisé, utilisés lorsque la
RH/l'Admin crée un nouvel employé (cahier des charges v8).
"""
import re
import secrets
import string
import unicodedata

from .models import User


def _slugify_ascii(value):
    """Translitère en ASCII simple (accents retirés) et ne garde que a-z0-9."""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", value.lower())


def generate_username(first_name, last_name):
    """Génère un identifiant unique du type 'prenom.nom', avec suffixe
    numérique en cas de collision (prenom.nom2, prenom.nom3, ...)."""
    base = f"{_slugify_ascii(first_name)}.{_slugify_ascii(last_name)}".strip(".")
    if not base:
        base = "utilisateur"

    username = base
    counter = 2
    while User.objects.filter(username=username).exists():
        username = f"{base}{counter}"
        counter += 1
    return username


def generate_temporary_password(length=12):
    """Mot de passe temporaire aléatoire et sécurisé (lettres + chiffres +
    au moins un caractère spécial), à faire changer dès la première connexion."""
    alphabet = string.ascii_letters + string.digits
    password = "".join(secrets.choice(alphabet) for _ in range(length - 2))
    # on garantit au moins un chiffre et un caractère spécial pour la robustesse
    password += secrets.choice(string.digits)
    password += secrets.choice("!@#$%&*")
    return "".join(secrets.SystemRandom().sample(password, len(password)))
