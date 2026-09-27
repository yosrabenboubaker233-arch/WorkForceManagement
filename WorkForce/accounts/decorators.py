from functools import wraps
from django.core.exceptions import PermissionDenied


def role_required(*roles):
    """Autorise l'accès uniquement aux utilisateurs ayant l'un des rôles indiqués.
    Un superutilisateur Django (is_superuser=True) passe toujours — pratique
    pour l'administration technique générale de l'application."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                raise PermissionDenied
            if request.user.role not in roles and not request.user.is_superuser:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def strict_role_required(*roles):
    """Variante de `role_required` qui ne laisse PAS passer les superutilisateurs
    Django automatiquement. À utiliser pour les actions métier réservées à un
    rôle précis (ex : valider/approuver/appliquer une augmentation de salaire),
    où le rôle « Admin » (Super Administrateur) ne doit avoir aucun droit
    métier — seulement une supervision en lecture."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                raise PermissionDenied
            if request.user.role not in roles:
                raise PermissionDenied
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator