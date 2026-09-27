from django.urls import path
from . import views

app_name = "leaves"

urlpatterns = [
    # Congés
    path("nouvelle-demande/", views.leave_request_create, name="create"),
    path("mes-demandes/", views.my_requests, name="my_requests"),
    path("<int:pk>/annuler/", views.leave_cancel, name="cancel"),
    path("<int:pk>/modifier/", views.leave_edit, name="edit"),
    path("<int:pk>/supprimer/", views.leave_delete, name="delete"),
    path("a-valider/", views.validation_inbox, name="validation_inbox"),
    path("<int:pk>/traiter-etape1/<str:decision>/", views.leave_decide_step1, name="decide_step1"),
    path("<int:pk>/traiter-etape2/<str:decision>/", views.leave_decide_step2, name="decide_step2"),
    path("historique/", views.leave_history, name="history"),

    # Autorisations d'absence
    path("autorisations/nouvelle-demande/", views.authorization_create, name="authorization_create"),
    path("autorisations/mes-demandes/", views.my_authorizations, name="my_authorizations"),
    path("autorisations/<int:pk>/modifier/", views.authorization_edit, name="authorization_edit"),
    path("autorisations/<int:pk>/supprimer/", views.authorization_delete, name="authorization_delete"),
    path("autorisations/<int:pk>/traiter-etape1/<str:decision>/", views.authorization_decide_step1, name="authorization_decide_step1"),
    path("autorisations/<int:pk>/traiter-etape2/<str:decision>/", views.authorization_decide_step2, name="authorization_decide_step2"),
    path("autorisations/historique/", views.authorization_history, name="authorization_history"),
    path("autorisations/<int:pk>/traitement-paie/", views.authorization_set_treatment, name="authorization_set_treatment"),
]
