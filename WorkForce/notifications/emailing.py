"""
Utilitaire central pour l'envoi d'email lié à une notification applicative.

Le cahier des charges v3 (§10) impose que TOUTE notification applicative
importante (congé, autorisation, alerte d'absence, salaire, tâche) déclenche
automatiquement un email correspondant, et qu'un échec d'envoi ne fasse
jamais disparaître la notification côté application.

Toutes les vues du projet doivent créer la Notification via
Notification.objects.create(...) PUIS appeler send_notification_email(notif)
juste après, plutôt que de dupliquer la logique d'envoi.
"""
from django.core.mail import send_mail
from django.conf import settings


def send_notification_email(notification):
    """Envoie un email reprenant le contenu d'une Notification déjà créée.

    Ne lève jamais d'exception : en cas d'échec (pas de SMTP configuré,
    adresse invalide...), la notification reste de toute façon visible
    dans l'application — c'est le comportement voulu par le cahier des
    charges ("en cas d'échec d'envoi, la notification reste visible").
    """
    recipient = notification.recipient
    if not recipient.email:
        return False

    try:
        send_mail(
            subject=f"[Workforce Management] {notification.title}",
            message=(
                f"Bonjour {recipient.get_full_name() or recipient.username},\n\n"
                f"{notification.message}\n\n"
                f"Consultez le détail depuis votre espace Workforce Management.\n"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient.email],
            fail_silently=True,
        )
        return True
    except Exception:
        return False


def notify(recipient, category, title, message, link=""):
    """Raccourci : crée la Notification in-app ET envoie l'email associé
    en un seul appel. Retourne la Notification créée."""
    from .models import Notification  # import local pour éviter les imports circulaires

    notification = Notification.objects.create(
        recipient=recipient, category=category, title=title, message=message, link=link,
    )
    send_notification_email(notification)
    return notification


def send_welcome_email(user, temporary_password, login_url="http://127.0.0.1:8000/login/"):
    """Envoie à un NOUVEL utilisateur son nom d'utilisateur et son mot de
    passe temporaire, à l'adresse email saisie par la RH/l'Admin lors de
    la création de son compte (cahier des charges v8).

    Retourne True/False selon que l'envoi a réussi — contrairement à
    notify(), l'appelant doit vérifier ce retour car sans email, l'employé
    n'a AUCUN autre moyen de connaître son mot de passe initial.
    """
    if not user.email:
        return False

    try:
        send_mail(
            subject="[Workforce Management] Votre compte a été créé — identifiants de connexion",
            message=(
                f"Bonjour {user.get_full_name() or user.username},\n\n"
                f"Un compte Workforce Management vient d'être créé pour vous.\n\n"
                f"Nom d'utilisateur : {user.username}\n"
                f"Mot de passe temporaire : {temporary_password}\n\n"
                f"Connectez-vous ici : {login_url}\n\n"
                f"⚠️ Pour votre sécurité, merci de changer ce mot de passe dès votre "
                f"première connexion (menu en haut à droite > Changer mon mot de passe).\n"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        return True
    except Exception:
        return False
