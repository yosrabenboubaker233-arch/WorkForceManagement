from django.urls import path
from . import views

app_name = "attendance"

urlpatterns = [
    path("checkin/", views.checkin_page, name="checkin"),
    path("mes-presences/", views.my_attendance, name="my_attendance"),
    path("equipe/", views.team_dashboard, name="team_dashboard"),
    path("rapport/<int:attendance_id>/supprimer/", views.supprimer_rapport_teletravail, name="supprimer_rapport"),
    path("alertes/", views.alerts_list, name="alerts"),
    path("alertes/<int:pk>/resoudre/", views.alert_resolve, name="alert_resolve"),

    # Enregistrement d'un poste (IT/RH uniquement, une fois par PC)
    path("postes/<int:poste_id>/enregistrer/", views.enregistrer_poste, name="enregistrer_poste"),
]