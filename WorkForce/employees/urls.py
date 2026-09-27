from django.urls import path
from . import views

app_name = "employees"

urlpatterns = [
    path("", views.employee_list, name="list"),
    path("mon-profil/", views.my_profile, name="my_profile"),
    path("organigramme/", views.org_chart, name="org_chart"),
    path("nouveau/", views.employee_create, name="create"),
    path("<int:pk>/", views.employee_detail, name="detail"),
    path("<int:pk>/modifier/", views.employee_edit, name="edit"),
    path("<int:pk>/supprimer/", views.employee_delete, name="delete"),
    path("<int:pk>/document/", views.document_upload, name="document_upload"),
    path("document/<int:doc_id>/modifier/", views.document_edit, name="document_edit"),
    path("document/<int:doc_id>/supprimer/", views.document_delete, name="document_delete"),
    path("<int:pk>/historique/", views.history_add, name="history_add"),
    path("<int:pk>/contrat/nouveau/", views.contract_create, name="contract_create"),
    path("contrat/<int:contract_id>/", views.contract_detail, name="contract_detail"),
    path("contrat/<int:contract_id>/modifier/", views.contract_edit, name="contract_edit"),
    path("contrat/<int:contract_id>/cloturer/", views.contract_end, name="contract_end"),
        path("contrat/<int:contract_id>/supprimer/", views.contract_delete, name="contract_delete"),
]