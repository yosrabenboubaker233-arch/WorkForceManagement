from django.urls import path
from . import views

app_name = "payroll"

urlpatterns = [
    path("", views.salary_list, name="list"),
    path("export-groupe/", views.payslip_bulk_export, name="bulk_export"),
    path("ma-remuneration/", views.my_salary, name="my_salary"),
    path("file-attente/", views.payroll_queue, name="queue"),
    path("file-attente/<str:kind>/<int:pk>/traiter/", views.payroll_mark_processed, name="mark_processed"),
    path("masse-salariale/", views.payroll_overview, name="overview"),

    # Workflow d'augmentation : Manager -> RH -> Direction -> Paie
    path("propositions/", views.proposal_list, name="proposal_list"),
    path("propositions/nouvelle/", views.proposal_new, name="proposal_new"),
    path("propositions/<int:pk>/valider-rh/", views.proposal_rh_validate, name="proposal_rh_validate"),
    path("propositions/<int:pk>/rejeter-rh/", views.proposal_rh_reject, name="proposal_rh_reject"),
    path("propositions/<int:pk>/approuver-direction/", views.proposal_direction_approve, name="proposal_direction_approve"),
    path("propositions/<int:pk>/rejeter-direction/", views.proposal_direction_reject, name="proposal_direction_reject"),
    path("propositions/<int:pk>/appliquer/", views.proposal_apply, name="proposal_apply"),

    path("<int:pk>/", views.salary_detail, name="detail"),
    path("<int:pk>/modifier/", views.salary_edit, name="edit"),
    path("<int:pk>/augmentation/", views.add_raise, name="add_raise"),
    path("<int:pk>/proposer-augmentation/", views.proposal_create, name="proposal_create"),
    path("<int:pk>/fiche-de-paie/", views.payslip_export, name="payslip_export"),
    path("bulletin/<int:pk>/valider/", views.payslip_validate, name="payslip_validate"),

    # Barème de paie (CNSS/CSS/IRPP) — géré par la Paie
    path("bareme/", views.payroll_rates_list, name="rates_list"),
    path("bareme/nouveau/", views.payroll_rate_create, name="rate_create"),

    # Politique de paie (heures sup., taux horaire, jour de repos, limite interne) + jours fériés
    path("politique/", views.payroll_policy_view, name="policy_view"),
    path("politique/modifier/", views.payroll_policy_edit, name="policy_edit"),
    path("politique/jour-ferie/nouveau/", views.public_holiday_create, name="holiday_create"),

]