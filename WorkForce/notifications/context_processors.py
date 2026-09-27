def unread_notifications(request):
    """Rend le nombre de notifications non lues disponible dans tous les templates."""
    if request.user.is_authenticated:
        count = request.user.notifications.filter(is_read=False).count()
        return {"unread_notifications_count": count}
    return {"unread_notifications_count": 0}
