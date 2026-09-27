
from datetime import datetime

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from accounts.decorators import role_required
from .models import Attendance, AbsenceAlert, PosteAutorise
from .forms import AbsenceAlertResolveForm
from employees.models import Employee
from leaves.models import LeaveRequest, Authorization


def _get_or_create_today_attendance(employee):
    today = timezone.localdate()
    attendance, _ = Attendance.objects.get_or_create(
        employee=employee, date=today, defaults={"status": Attendance.Status.ABSENT}
    )
    return attendance

def _envoyer_rapport_au_manager(attendance):
    """Transmet le rapport de travail du jour (télétravail) au manager de
    l'employé, une fois le départ pointé — notification + email, comme le
    reste des alertes de pointage."""
    from notifications.models import Notification
    from notifications.emailing import notify

    employee = attendance.employee
    manager_user = employee.manager.user if employee.manager else None
    if not manager_user or not attendance.rapport_teletravail:
        return

    notify(
        recipient=manager_user,
        category=Notification.Category.OTHER,
        title="Rapport de télétravail reçu",
        message=(
            f"{employee} a pointé son départ en télétravail le {attendance.date} "
            f"et a déposé son rapport de travail du jour."
        ),
        link=f"/pointage/equipe/?date={attendance.date.isoformat()}",
    )
    
def _resolve_missing_checkin_alert(attendance):
    """Un pointage tardif résout automatiquement une alerte MISSING_CHECKIN
    déjà émise (§8) : l'absence n'est jamais confirmée dans ce cas, et la RH
    /le manager sont informés que l'employé est finalement présent."""
    from accounts.models import User
    from notifications.models import Notification
    from notifications.emailing import send_notification_email

    alert = AbsenceAlert.objects.filter(
        employee=attendance.employee, date=attendance.date,
        kind=AbsenceAlert.Kind.MISSING_CHECKIN, resolved=False,
    ).first()
    if not alert:
        return

    alert.resolved = True
    alert.save(update_fields=["resolved"])

    message = (
        f"{attendance.employee} a pointé à {attendance.check_in.strftime('%H:%M')}. Il/elle est présent(e)."
    )
    manager_user = attendance.employee.manager.user if attendance.employee.manager else None
    hr_users = User.objects.filter(role__in=[User.Role.RH, User.Role.ADMIN])
    for user in {u for u in [manager_user] if u} | set(hr_users):
        notif = Notification.objects.create(
            recipient=user,
            category=Notification.Category.OTHER,
            title="Pointage régularisé",
            message=message,
            link="/pointage/alertes/",
        )
        send_notification_email(notif)


def _appliquer_pointage(attendance, action):
    """
    Enregistre arrivée, départ, ou pause. Toujours horodaté côté serveur
    (jamais par le navigateur) pour éviter toute falsification.
    """

    now = timezone.localtime().time()

    if action == "check_in" and not attendance.check_in:

        attendance.check_in = now
        attendance.status = Attendance.Status.PRESENT
        attendance.save()
        _resolve_missing_checkin_alert(attendance)

        return f"Arrivée pointée à {now.strftime('%H:%M')}."


    if action == "check_out" and attendance.check_in and not attendance.check_out:

        attendance.check_out = now
        attendance.save()

        return f"Départ pointé à {now.strftime('%H:%M')}."


    if action == "pause_start" and attendance.check_in and not attendance.check_out and not attendance.pause_start:
        attendance.pause_start = now
        attendance.save()
        return f"Début de pause pointé à {now.strftime('%H:%M')}."


    if action == "pause_end" and attendance.pause_start and not attendance.pause_end:
        attendance.pause_end = now
        attendance.save()
        return f"Fin de pause pointée à {now.strftime('%H:%M')}."


    return None


def _poste_depuis_cookie(request):
    """
    Renvoie le PosteAutorise correspondant au cookie déposé sur ce navigateur,
    ou None si absent/inconnu/désactivé.
    """
    cookie_recu = request.COOKIES.get("poste_id")
    if not cookie_recu:
        return None
    return PosteAutorise.objects.filter(cookie_secret=cookie_recu, actif=True).first()


@login_required
def checkin_page(request):

    employee = getattr(request.user, "employee_profile", None)

    if not employee:
        messages.error(request, "Aucun dossier employé associé à ce compte.")
        return redirect("accounts:dashboard")

    if request.user.role == "DIRECTION":
        messages.info(request, "Le pointage ne concerne pas la Direction Générale.")
        return redirect("accounts:dashboard")


    attendance = _get_or_create_today_attendance(employee)


    if request.method == "POST":

        action = request.POST.get("action")
        lieu = request.POST.get("lieu")


        # ==========================
        # BUREAU
        # ==========================

        if lieu == "bureau":

            poste = _poste_depuis_cookie(request)

            if not poste:
                return HttpResponseForbidden(
                    "Ce poste n'est pas autorisé."
                )


            message = _appliquer_pointage(
                attendance,
                action
            )


            if message:

                attendance.lieu = Attendance.Lieu.BUREAU
                attendance.save()

                poste.derniere_utilisation = timezone.now()
                poste.ip_derniere_connexion = request.META.get(
                    "REMOTE_ADDR"
                )
                poste.save(
                    update_fields=[
                        "derniere_utilisation",
                        "ip_derniere_connexion"
                    ]
                )


                messages.success(
                    request,
                    message
                )


            return redirect(
                "attendance:checkin"
            )



        # ==========================
        # TELETRAVAIL
        # ==========================
        if lieu == "teletravail":
    
            # Avant de pointer le DÉPART en télétravail, l'employé doit
            # obligatoirement déposer son rapport de travail du jour —
            # celui-ci est ensuite envoyé automatiquement à son manager.
            if action == "check_out" and not attendance.check_out:
                rapport = request.FILES.get("rapport")
                if not rapport and not attendance.rapport_teletravail:
                    messages.error(
                        request,
                        "Vous devez déposer votre rapport de travail avant de pointer votre départ (télétravail)."
                    )
                    return redirect("attendance:checkin")
                if rapport:
                    attendance.rapport_teletravail = rapport
                    attendance.save(update_fields=["rapport_teletravail"])

            message = _appliquer_pointage(
                attendance,
                action
            )


            if message:

                attendance.lieu = Attendance.Lieu.TELETRAVAIL
                attendance.save()

                if action == "check_out":
                    _envoyer_rapport_au_manager(attendance)

                messages.success(
                    request,
                    f"{message} (télétravail)"
                )


            return redirect(
                "attendance:checkin"
            )

    history = Attendance.objects.filter(
        employee=employee
    ).order_by("-date")[:14]


    return render(
        request,
        "attendance/checkin.html",
        {
            "attendance": attendance,
            "history": history,
        },
    )


@login_required
def my_attendance(request):
    """Permet à l'employé de consulter l'historique de SA PROPRE présence,
    filtré sur une date (ou une période) qu'il saisit lui-même dans un
    formulaire de recherche. Par défaut : le mois en cours."""
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        messages.error(request, "Aucun dossier employé associé à ce compte.")
        return redirect("accounts:dashboard")

    today = timezone.localdate()
    date_debut_str = request.GET.get("date_debut")
    date_fin_str = request.GET.get("date_fin")

    def _parse(date_str, default):
        if not date_str:
            return default
        try:
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return default

    date_debut = _parse(date_debut_str, today.replace(day=1))
    date_fin = _parse(date_fin_str, today)
    if date_debut > date_fin:
        date_debut, date_fin = date_fin, date_debut

    records = Attendance.objects.filter(
        employee=employee, date__range=(date_debut, date_fin)
    ).order_by("-date")

    nb_present = records.filter(status=Attendance.Status.PRESENT).count()
    nb_absent = records.filter(status=Attendance.Status.ABSENT).count()
    nb_retard = records.filter(status=Attendance.Status.LATE).count()

    return render(request, "attendance/my_attendance.html", {
        "records": records, "date_debut": date_debut, "date_fin": date_fin,
        "nb_present": nb_present, "nb_absent": nb_absent, "nb_retard": nb_retard,
    })
@staff_member_required
def enregistrer_poste(request, poste_id):
    poste = get_object_or_404(PosteAutorise, id=poste_id, actif=True)
    response = HttpResponse(
        f"Poste « {poste.nom} » enregistré avec succès sur ce navigateur.\n"
        f"Ne fermez/rouvrez pas ce message : le cookie est déjà déposé."
    )
    from django.conf import settings as dj_settings
    response.set_cookie(
        "poste_id",
        poste.cookie_secret,
        max_age=None,
        httponly=True,
        secure=not dj_settings.DEBUG,
        samesite="Strict",
    )
    return response

@login_required
@role_required("MANAGER", "ADMIN")
def supprimer_rapport_teletravail(request, attendance_id):
    """Supprime le rapport de télétravail déposé par un employé — réservé à
    son manager direct (le rapport n'étant lui-même visible que par lui,
    voir team_dashboard.html)."""
    attendance = get_object_or_404(Attendance, pk=attendance_id)
    manager_profile = getattr(request.user, "employee_profile", None)
    if attendance.employee.manager_id != getattr(manager_profile, "id", None):
        messages.error(request, "Vous ne pouvez supprimer que les rapports des membres de votre équipe.")
        return redirect("attendance:team_dashboard")

    if request.method == "POST":
        attendance.rapport_teletravail.delete(save=True)
        messages.success(request, f"Rapport de {attendance.employee} supprimé.")
    return redirect(f"/pointage/equipe/?date={attendance.date.isoformat()}")

@login_required
@role_required("MANAGER", "RH", "ADMIN", "PAYROLL")
def team_dashboard(request):
    date_str = request.GET.get("date")
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            selected_date = timezone.localdate()
    else:
        selected_date = timezone.localdate()

    employees = Employee.objects.select_related("user")
    if request.user.role == "MANAGER":
        manager_profile = getattr(request.user, "employee_profile", None)
        employees = employees.filter(manager=manager_profile)

    day_records = {a.employee_id: a for a in Attendance.objects.filter(date=selected_date)}
    leaves_today = {
        lr.employee_id: lr for lr in LeaveRequest.objects.filter(
            status=LeaveRequest.Status.APPROVED, start_date__lte=selected_date, end_date__gte=selected_date,
        )
    }
    authorizations_today = {
        a.employee_id: a for a in Authorization.objects.filter(
            status=Authorization.Status.APPROVED, date=selected_date,
        )
    }

    rows = []
    nb_present, nb_absent, nb_conge, nb_autorisation = 0, 0, 0, 0
    for emp in employees:
        attendance = day_records.get(emp.id)
        leave = leaves_today.get(emp.id)
        authorization = authorizations_today.get(emp.id)

        if leave:
            situation = "leave"
            nb_conge += 1
        elif authorization:
            situation = "authorization"
            nb_autorisation += 1
        elif attendance and attendance.check_in:
            situation = "present"
            nb_present += 1
        else:
            situation = "absent"
            nb_absent += 1

        rows.append({
            "employee": emp, "attendance": attendance, "leave": leave,
            "authorization": authorization, "situation": situation,
        })

    return render(request, "attendance/team_dashboard.html", {
        "rows": rows, "selected_date": selected_date,
        "nb_present": nb_present, "nb_absent": nb_absent,
        "nb_conge": nb_conge, "nb_autorisation": nb_autorisation,
    })


@login_required
@role_required("MANAGER", "RH", "ADMIN")
def alerts_list(request):
    """Liste des alertes d'absence/retard/pointage manquant, filtrable par
    date précise OU par mois/année (paramètres GET `date`, ou `month`+`year`),
    pour faciliter la vérification."""
    alerts = AbsenceAlert.objects.select_related("employee__user").order_by("resolved", "-created_at")
    if request.user.role == "MANAGER":
        manager_profile = getattr(request.user, "employee_profile", None)
        alerts = alerts.filter(employee__manager=manager_profile)

    date_filtre = request.GET.get("date")
    mois_filtre = request.GET.get("month")
    annee_filtre = request.GET.get("year")

    if date_filtre:
        try:
            alerts = alerts.filter(date=datetime.strptime(date_filtre, "%Y-%m-%d").date())
        except ValueError:
            date_filtre = None
    elif mois_filtre and annee_filtre:
        try:
            mois_filtre, annee_filtre = int(mois_filtre), int(annee_filtre)
            alerts = alerts.filter(date__month=mois_filtre, date__year=annee_filtre)
        except (TypeError, ValueError):
            mois_filtre, annee_filtre = None, None
    else:
        mois_filtre, annee_filtre = None, None

    return render(request, "attendance/alerts_list.html", {
        "alerts": alerts,
        "selected_date": date_filtre, "selected_month": mois_filtre, "selected_year": annee_filtre,
        "mois_choices": [
            (1, "Janvier"), (2, "Février"), (3, "Mars"), (4, "Avril"), (5, "Mai"), (6, "Juin"),
            (7, "Juillet"), (8, "Août"), (9, "Septembre"), (10, "Octobre"), (11, "Novembre"), (12, "Décembre"),
        ],
    })

@login_required
@role_required("RH", "ADMIN")
def alert_resolve(request, pk):
    """La RH statue sur une absence non couverte (§7) : justifiée ou non, et
    son impact paie (déductible / à récupérer / aucune déduction). Le
    manager peut consulter les alertes (alerts_list) mais ne décide plus
    seul du traitement paie — réservé à la RH/Admin."""
    alert = get_object_or_404(AbsenceAlert, pk=pk)
    form = AbsenceAlertResolveForm(request.POST or None, instance=alert)
    if request.method == "POST" and form.is_valid():
        form.save(commit=False)
        alert.resolved = True
        alert.save()
        messages.success(request, "Alerte traitée : justification et impact paie enregistrés.")
        return redirect("attendance:alerts")
    return render(request, "attendance/alert_resolve.html", {"form": form, "alert": alert})