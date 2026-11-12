"""
Django settings for teamdev_hr project.
Workforce Management — Plateforme de gestion des ressources humaines
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "django-insecure-CHANGE-THIS-SECRET-KEY-IN-PRODUCTION"

DEBUG = True

# -----------------------------------------------------------------
# Email — notifications RH doublées par email (cahier des charges v3 §10).
# En développement : les emails s'affichent dans la console (aucun
# serveur SMTP requis). En production, basculez sur le backend SMTP
# commenté ci-dessous. Si l'envoi échoue, la notification reste de
# toute façon visible dans l'application (fail_silently côté vues).
# -----------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = "yossraboubaker61@gmail.com"          # ← votre adresse Gmail
EMAIL_HOST_PASSWORD = "nfqqfhqfobsonuyo"               # ← le mot de passe d'application (16 caractères, sans espaces)
EMAIL_TIMEOUT = 10   # secondes — évite qu'une commande (ex: detect_absences) reste bloquée
                      # indéfiniment si Gmail met du temps à répondre ou est injoignable.
DEFAULT_FROM_EMAIL = f"WorkForce Management <{EMAIL_HOST_USER}>"

# -----------------------------------------------------------------
# Pointage — horaires attendus et tolérances pour les alertes
# automatiques (commande `check_workday_alerts`, à lancer via cron
# toutes les 15-30 min pendant la matinée, ex :
#   */15 8-11 * * 1-5 cd /chemin/du/projet && python manage.py check_workday_alerts
# -----------------------------------------------------------------
from datetime import time as _time
WORKDAY_START = _time(9, 0)          # 8h00 en horaire d'été (géré dynamiquement, voir Attendance.expected_start)
WORKDAY_END = _time(17, 0)
LATE_GRACE_MINUTES = 10              # tolérance avant de considérer un pointage comme un retard
MISSING_CHECKIN_GRACE_HOURS = 1      # délai après le début de journée avant d'alerter sur un pointage manquant

# -----------------------------------------------------------------
# Paie — informations employeur figurant sur le bulletin de paie
# et taux réglementaires (simplifiés, à ajuster selon la législation
# en vigueur avant tout usage réel).
# -----------------------------------------------------------------
COMPANY_INFO = {
    "nom": "Workforce Management SARL",
    "matricule_fiscal": "0000000/A/M/000",
    "cnss": "000000-00",
    "adresse": "Adresse de la société, Tunis, Tunisie",
}
TAUX_CNSS_SALARIE = 0.0918   # 9,18 % — part salariale CNSS (Tunisie, simplifié)
TAUX_CSS_SALARIE = 0.005     # 0,5 % — Contribution Sociale de Solidarité (simplifié)
BAREME_IRPP = [               # tranches annuelles simplifiées (à ajuster selon le barème en vigueur)
    (5000, 0.00),
    (10000, 0.26),
    (20000, 0.28),
    (30000, 0.32),
    (50000, 0.35),
    (None, 0.38),
]

# EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
# EMAIL_HOST = "smtp.votre-fournisseur.com"
# EMAIL_PORT = 587
# EMAIL_USE_TLS = True
# EMAIL_HOST_USER = "no-reply@workforce-management.com"
# EMAIL_HOST_PASSWORD = "xxxxx"  # variable d'environnement en prod, jamais en dur

# -----------------------------------------------------------------
# Règles RH (cahier des charges v3 §5)
# -----------------------------------------------------------------
LEAVE_PREAVIS_JOURS = 2          # préavis minimum avant la date de début d'un congé
# Référence unique du congé annuel — toute la logique de solde (accrual
# mensuel, valeur par défaut à l'embauche) en dérive, pour éviter d'avoir
# plusieurs constantes non synchronisées dispersées dans le code.
ANNUAL_LEAVE_DAYS = 26

ALLOWED_HOSTS = os.environ.get(
    "DJANGO_ALLOWED_HOSTS",
    "yosrabenboubaker.me,www.yosrabenboubaker.me,localhost,127.0.0.1",
).split(",")

CSRF_TRUSTED_ORIGINS = [
    "https://yosrabenboubaker.me",
    "https://www.yosrabenboubaker.me",
]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# --- En-têtes et cookies de sécurité (DAST / OWASP ZAP) ---
SECURE_HSTS_SECONDS = 3600          # commencer par 1 h, puis 31536000 (1 an) une fois validé
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = os.environ.get("DJANGO_SECURE_COOKIES", "True") == "True"
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
X_FRAME_OPTIONS = "DENY"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    # Apps Workforce Management
    "accounts",
    "employees",
    "leaves",
    "attendance",
    "payroll",
    "notifications",
    "tasks",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
     # Filet de sécurité : déclenche les alertes de pointage (pointage
    # oublié, retard, absence) même si le planificateur APScheduler n'a
    # pas pu démarrer faute du paquet installé — voir attendance/middleware.py.
    "attendance.middleware.WorkdayCheckFallbackMiddleware",
]

ROOT_URLCONF = "teamdev_hr.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "notifications.context_processors.unread_notifications",
            ],
        },
    },
]

WSGI_APPLICATION = "teamdev_hr.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "data"  / "db.sqlite3",
    }
}
if os.environ.get("DB_HOST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME"),
            "USER": os.environ.get("DB_USER"),
            "PASSWORD": os.environ.get("DB_PASSWORD"),
            "HOST": os.environ.get("DB_HOST"),
            "PORT": os.environ.get("DB_PORT", "5432"),
            "OPTIONS": {"sslmode": "require"},
        }
    }

AUTH_USER_MODEL = "accounts.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Tunis"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:dashboard"
LOGOUT_REDIRECT_URL = "accounts:login"

AWS_STORAGE_BUCKET_NAME = os.environ.get("AWS_STORAGE_BUCKET_NAME")
if AWS_STORAGE_BUCKET_NAME:
    AWS_S3_REGION_NAME = "eu-north-1"
    AWS_S3_SIGNATURE_VERSION = "s3v4"
    AWS_S3_FILE_OVERWRITE = False
    AWS_QUERYSTRING_AUTH = True
    AWS_QUERYSTRING_EXPIRE = 3600
    STORAGES = {
        "default": {"BACKEND": "storages.backends.s3.S3Storage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
