from decimal import Decimal
import calendar
import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden
from django.utils import timezone

from accounts.decorators import role_required, strict_role_required
from accounts.models import User
from employees.models import Employee
from leaves.models import LeaveRequest, Authorization
from .models import Salary, SalaryHistory, SalaryIncreaseProposal, PayslipRecord, PayrollRateSet, PayrollPolicy, PublicHoliday
from .forms import (
    RaiseForm, SalaryEditForm, SalaryProposalForm, SalaryProposalNewForm,
    ProposalDecisionForm, ProposalValidateForm, PayrollRateSetForm, PayrollRateBracketFormSet,
    PayrollPolicyForm, PublicHolidayForm,
)
from notifications.models import Notification
from notifications.emailing import notify
from .utils import build_payslip
from .pdf import render_payslip_pdf


def _apply_increase(employee, salary, increase_type, value, effective_date, reason, decided_by, decided_label=""):
    """Historise une augmentation dans SalaryHistory, avec sa date d'effet.

    Ne touche plus Salary.base_amount directement : ce champ est désormais
    resynchronisé automatiquement (signal payroll.signals) à partir de
    Contract + SalaryHistory, pour la date du jour. Une augmentation dont la
    date d'effet est future n'impacte donc pas immédiatement le salaire
    affiché — exactement le comportement attendu.
    """
    from .contract_utils import get_effective_base_salary

    previous = get_effective_base_salary(employee, effective_date)
    if previous is None:
        previous = salary.base_amount  # employé sans contrat renseigné : on garde l'ancien comportement

    if increase_type == SalaryHistory.IncreaseType.PERCENTAGE:
        new_amount = (previous * (Decimal("1") + value / Decimal("100"))).quantize(Decimal("0.01"))
        percentage = value
    else:
        new_amount = value
        percentage = ((new_amount - previous) / previous * 100) if previous else Decimal("0")

    history = SalaryHistory.objects.create(
        employee=employee,
        previous_amount=previous,
        new_amount=new_amount,
        percentage=round(percentage, 2),
        increase_type=increase_type,
        effective_date=effective_date,
        reason=reason,
        decided_by=decided_label or (decided_by.get_full_name() or decided_by.username),
        approved_by=decided_by,
    )
    # Salary.base_amount est recalculé par le signal post_save de SalaryHistory
    # (voir payroll/signals.py) ; on rafraîchit l'instance en mémoire pour que
    # l'appelant voie la valeur à jour si la date d'effet est aujourd'hui ou passée.
    salary.refresh_from_db(fields=["base_amount"])

    notify(
        recipient=employee.user,
        category=Notification.Category.SALARY_UPDATE,
        title="Mise à jour de votre rémunération",
        message=(
            f"Votre salaire de base passe de {previous} à {new_amount} "
            f"à partir du {effective_date}."
        ),
        link=f"/paie/{employee.pk}/",
    )
    return history


def _notify_users(role_or_roles, category, title, message, link):
    roles = [role_or_roles] if isinstance(role_or_roles, str) else role_or_roles
    for user in User.objects.filter(role__in=roles):
        notify(recipient=user, category=category, title=title, message=message, link=link)


@login_required
@role_required("PAYROLL", "RH")
def payroll_queue(request):
    """File d'attente Paie : congés et autorisations APPROUVÉS restant à
    traiter en paie. La Paie ne peut PAS approuver/refuser — seulement
    marquer « Traité » une fois pris en compte (cahier des charges v4).

    Filtrable par mois/année (paramètres GET `month`/`year`) pour faciliter
    la vérification mois par mois avant de clôturer les bulletins."""
    leaves = LeaveRequest.objects.filter(
        status=LeaveRequest.Status.APPROVED
    ).select_related("employee__user").order_by("payroll_status", "-step1_decided_at")
    authorizations = Authorization.objects.filter(
        status=Authorization.Status.APPROVED
    ).select_related("employee__user").order_by("payroll_status", "-step1_decided_at")

    mois_filtre = request.GET.get("month")
    annee_filtre = request.GET.get("year")
    if mois_filtre and annee_filtre:
        try:
            mois_filtre, annee_filtre = int(mois_filtre), int(annee_filtre)
            dernier_jour = calendar.monthrange(annee_filtre, mois_filtre)[1]
            debut_mois = date(annee_filtre, mois_filtre, 1)
            fin_mois = date(annee_filtre, mois_filtre, dernier_jour)
            leaves = leaves.filter(start_date__lte=fin_mois, end_date__gte=debut_mois)
            authorizations = authorizations.filter(date__gte=debut_mois, date__lte=fin_mois)
        except (TypeError, ValueError):
            mois_filtre, annee_filtre = None, None
    else:
        mois_filtre, annee_filtre = None, None

    return render(request, "payroll/queue.html", {
        "leaves": leaves, "authorizations": authorizations,
        "selected_month": mois_filtre, "selected_year": annee_filtre,
        "mois_choices": [
            (1, "Janvier"), (2, "Février"), (3, "Mars"), (4, "Avril"), (5, "Mai"), (6, "Juin"),
            (7, "Juillet"), (8, "Août"), (9, "Septembre"), (10, "Octobre"), (11, "Novembre"), (12, "Décembre"),
        ],
    })

@login_required
@strict_role_required("PAYROLL")
def payroll_mark_processed(request, kind, pk):
    model = LeaveRequest if kind == "conge" else Authorization
    obj = get_object_or_404(model, pk=pk)
    obj.mark_payroll_processed(request.user)
    messages.success(request, "Marqué comme traité en paie.")
    return redirect("payroll:queue")


@login_required
def my_salary(request):
    """Point d'entrée pour l'Employé : consultation en lecture seule de sa
    propre rémunération (salaire, historique des augmentations, bulletins).
    Redirige simplement vers la fiche détail de son propre dossier Employee."""
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        messages.error(request, "Aucun dossier employé associé à ce compte.")
        return redirect("accounts:dashboard")
    return redirect("payroll:detail", pk=employee.pk)


@login_required
@role_required("PAYROLL", "RH", "DIRECTION")
def salary_list(request):
    """Liste tous les employés actifs. Ceux dont le compte a été créé par
    l'Admin/RH mais qui n'ont pas encore de fiche de paie apparaissent
    comme « Non configuré » — c'est la Paie qui les intègre au système de
    paie en leur définissant un salaire de base initial."""
    employees = Employee.objects.filter(status=Employee.Status.ACTIVE).select_related(
        "user", "department", "salary"
    ).order_by("user__last_name", "user__first_name")
    return render(request, "payroll/salary_list.html", {"employees": employees})

@login_required
@strict_role_required("PAYROLL")
def payslip_bulk_export(request):
    """Téléchargement groupé des bulletins de paie : la Paie choisit un mois
    et sélectionne les salariés concernés (ou « Tout sélectionner »), et
    reçoit un fichier ZIP contenant un PDF par salarié — pour éviter de
    cliquer « Télécharger » un par un.

    Reprend exactement les mêmes règles que le téléchargement individuel
    (payslip_export) : mois obligatoirement terminé, sinon l'employé est
    ignoré avec un message ; s'il n'a aucun contrat couvrant ce mois, il
    est également ignoré (jamais de bulletin fabriqué à partir du salaire
    actuel pour un mois hors contrat)."""
    employees = Employee.objects.filter(status=Employee.Status.ACTIVE).select_related(
        "user", "department", "salary"
    ).order_by("user__last_name", "user__first_name")

    today = timezone.localdate()
    mois_choices = [
        (1, "Janvier"), (2, "Février"), (3, "Mars"), (4, "Avril"), (5, "Mai"), (6, "Juin"),
        (7, "Juillet"), (8, "Août"), (9, "Septembre"), (10, "Octobre"), (11, "Novembre"), (12, "Décembre"),
    ]

    if request.method == "POST":

        try:
            mois = int(request.POST.get("month", today.month))
            annee = int(request.POST.get("year", today.year))
        except (TypeError, ValueError):
            mois, annee = today.month, today.year
        ids_selectionnes = request.POST.getlist("employee_ids")

        dernier_jour_mois = calendar.monthrange(annee, mois)[1]
        fin_mois = date(annee, mois, dernier_jour_mois)
        if fin_mois >= today:
            messages.error(
                request,
                f"Le mois {mois:02d}/{annee} n'est pas encore terminé : impossible de générer les bulletins."
            )
            return redirect("payroll:bulk_export")

        if not ids_selectionnes:
            messages.error(request, "Sélectionnez au moins un salarié.")
            return redirect("payroll:bulk_export")

        selection = employees.filter(pk__in=ids_selectionnes)

        buffer = io.BytesIO()
        nb_ok, ignores = 0, []
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for employee in selection:
                salary, _ = Salary.objects.get_or_create(employee=employee, defaults={"base_amount": 0})
                payslip = build_payslip(salary, month=mois, year=annee)

                if payslip["hors_contrat"]:
                    ignores.append(f"{employee} (aucun contrat actif ce mois-ci)")
                    continue

                existing = PayslipRecord.objects.filter(employee=employee, month=mois, year=annee).first()
                if not (existing and existing.status == PayslipRecord.Status.VALIDATED):
                    PayslipRecord.objects.update_or_create(
                        employee=employee, month=mois, year=annee,
                        defaults={
                            "gross_amount": payslip["salaire_brut"],
                            "deductions_amount": payslip["total_retenues"],
                            "net_amount": payslip["salaire_net"],
                            "generated_by": request.user,
                            "base_salary_used": payslip["salaire_base"],
                            "hourly_rate_used": payslip["taux_horaire"],
                            "expected_hours_used": payslip["heures_prevues"],
                            "worked_hours_used": payslip["heures_travaillees"],
                            "overtime_hours_used": payslip["heures_sup"],
                            "overtime_amount_used": payslip["montant_heures_sup"],
                            "absence_deduction_used": payslip["retenue_absences"],
                        },
                    )

                pdf_bytes = render_payslip_pdf(payslip)
                nom_fichier = f"bulletin_paie_{employee.matricule}_{mois:02d}_{annee}.pdf"
                archive.writestr(nom_fichier, pdf_bytes)
                nb_ok += 1

        if nb_ok == 0:
            messages.error(request, "Aucun bulletin n'a pu être généré (voir les salariés ignorés).")
            return redirect("payroll:bulk_export")

        if ignores:
            messages.info(request, f"{len(ignores)} salarié(s) ignoré(s) (pas de contrat ce mois-ci) : " + ", ".join(ignores))

        buffer.seek(0)
        response = HttpResponse(buffer.read(), content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="bulletins_paie_{mois:02d}_{annee}.zip"'
        return response

    return render(request, "payroll/bulk_export.html", {
        "employees": employees, "mois_choices": mois_choices,
        "default_month": today.month, "default_year": today.year,
    })
    
def _pending_payroll_items(employee, month, year):
    """Congés/autorisations APPROUVÉS mais encore « À traiter » (non
    marqués « Traité » par la Paie) pour cet employé sur ce mois — utilisé
    à la fois pour bloquer la validation du bulletin (payslip_validate)
    et pour prévenir la Paie en amont sur la fiche employé."""
    nb_jours_mois = calendar.monthrange(year, month)[1]
    debut_mois = date(year, month, 1)
    fin_mois = date(year, month, nb_jours_mois)
    nb_conges = LeaveRequest.objects.filter(
        employee=employee, status=LeaveRequest.Status.APPROVED,
        payroll_status=LeaveRequest.PayrollStatus.TO_PROCESS,
        start_date__lte=fin_mois, end_date__gte=debut_mois,
    ).count()
    nb_autorisations = Authorization.objects.filter(
        employee=employee, status=Authorization.Status.APPROVED,
        payroll_status=Authorization.PayrollStatus.TO_PROCESS,
        date__gte=debut_mois, date__lte=fin_mois,
    ).count()
    return nb_conges, nb_autorisations 
@login_required
@role_required("PAYROLL", "ADMIN", "RH", "DIRECTION", "MANAGER", "EMPLOYEE")
def salary_detail(request, pk):
    employee = get_object_or_404(Employee, pk=pk)

    if request.user.role == "MANAGER":
        manager_profile = getattr(request.user, "employee_profile", None)
        est_sa_propre_fiche = employee.pk == getattr(manager_profile, "pk", None)
        est_un_membre_de_son_equipe = employee.manager_id == getattr(manager_profile, "pk", None)
        if not (est_sa_propre_fiche or est_un_membre_de_son_equipe):
            return HttpResponseForbidden("Vous ne pouvez consulter que votre propre rémunération ou celle de votre équipe.")
        
    # Un employé (ou un Admin consultant sa propre fiche via « Ma
    # rémunération ») ne peut consulter que sa propre fiche, en lecture
    # seule — l'Admin n'a aucun droit métier sur la rémunération d'autrui.
    if request.user.role in ("EMPLOYEE", "ADMIN"):
        employee_profile = getattr(request.user, "employee_profile", None)
        if employee.pk != getattr(employee_profile, "pk", None):
            return HttpResponseForbidden("Vous ne pouvez consulter que votre propre rémunération.")
    salary = getattr(employee, "salary", None)
    history = employee.salary_history.all()
    today = timezone.localdate()
    mois, annee = _parse_month_year(request, today)
    est_mois_futur = (annee, mois) > (today.year, today.month)
    payslip_preview = None
    jours_couverts, jours_total_mois = None, None
    if salary and not est_mois_futur:
        payslip_preview = build_payslip(salary, month=mois, year=annee)
        from .calendar_utils import jours_couverts_mois
        jours_couverts, jours_total_mois = jours_couverts_mois(employee, annee, mois)
    payslips = employee.payslips.all()[:12]
    for p in payslips:
        p.nb_conges_attente, p.nb_autorisations_attente = _pending_payroll_items(employee, p.month, p.year)
    pending_proposals = employee.salary_proposals.exclude(
        status__in=[SalaryIncreaseProposal.Status.REJECTED, SalaryIncreaseProposal.Status.APPLIED]
    )
    can_propose = request.user.role == "DIRECTION" or (
        request.user.role == "MANAGER"
        and employee.manager_id == getattr(getattr(request.user, "employee_profile", None), "pk", None)
    )
    return render(request, "payroll/salary_detail.html", {
        "employee": employee, "salary": salary, "history": history,
        "payslip_preview": payslip_preview, "payslips": payslips,
        "pending_proposals": pending_proposals, "can_propose": can_propose,
        "selected_month": mois, "selected_year": annee, "is_future_month": est_mois_futur,
        "today_month": today.month, "today_year": today.year,
        "jours_couverts": jours_couverts, "jours_total_mois": jours_total_mois,
        "mois_choices": [
            (1, "Janvier"), (2, "Février"), (3, "Mars"), (4, "Avril"), (5, "Mai"), (6, "Juin"),
            (7, "Juillet"), (8, "Août"), (9, "Septembre"), (10, "Octobre"), (11, "Novembre"), (12, "Décembre"),
        ],
    })

@login_required
@strict_role_required("PAYROLL")
def salary_edit(request, pk):
    """Intégration au système de paie / modification de la composition du
    salaire (base, primes, indemnités...)."""
    employee = get_object_or_404(Employee, pk=pk)
    salary, created = Salary.objects.get_or_create(employee=employee, defaults={"base_amount": 0})
    form = SalaryEditForm(request.POST or None, instance=salary)
    if request.method == "POST" and form.is_valid():
        form.save()
        if created:
            messages.success(request, f"{employee} a été intégré(e) au système de paie.")
        else:
            messages.success(request, "Composition du salaire mise à jour.")
        return redirect("payroll:detail", pk=employee.pk)
    return render(request, "payroll/salary_edit_form.html", {"form": form, "employee": employee, "creating": created})


@login_required
@strict_role_required("PAYROLL")
def add_raise(request, pk):
    """Ajout direct d'une augmentation par la Paie — correction administrative
    hors circuit formel. Le canal recommandé reste la proposition initiée
    par le Manager, validée par la RH puis approuvée par la Direction."""
    employee = get_object_or_404(Employee, pk=pk)
    salary, _ = Salary.objects.get_or_create(employee=employee, defaults={"base_amount": 0})

    form = RaiseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        _apply_increase(
            employee, salary,
            form.cleaned_data["increase_type"], form.cleaned_data["value"],
            form.cleaned_data["effective_date"], form.cleaned_data["reason"], request.user,
            decided_label=f"Paie — {request.user.get_full_name() or request.user.username} (correction directe)",
        )
        messages.success(request, "Augmentation enregistrée, historisée et notifiée (application + email).")
        return redirect("payroll:detail", pk=employee.pk)

    return render(request, "payroll/add_raise.html", {"form": form, "employee": employee, "salary": salary})


# ---------------------------------------------------------------------
# Workflow d'augmentation : Manager -> RH -> Direction -> Paie 
# ---------------------------------------------------------------------

def _employee_queryset_for_manager(user):
    manager_profile = getattr(user, "employee_profile", None)
    return Employee.objects.filter(status=Employee.Status.ACTIVE, manager=manager_profile).select_related("user")


@login_required
@strict_role_required("MANAGER", "DIRECTION")
def proposal_create(request, pk):
    """Étape 1 — le Manager propose une augmentation pour un membre de son
    équipe, OU la Direction propose directement (voir _notify_proposal_stage
    pour la règle de saut d'étape qui en découle)."""
    employee = get_object_or_404(Employee, pk=pk)
    if request.user.role == "MANAGER":
        manager_profile = getattr(request.user, "employee_profile", None)
        if employee.manager_id != getattr(manager_profile, "pk", None):
            return HttpResponseForbidden("Vous ne pouvez proposer une augmentation que pour un membre de votre équipe.")

    salary = getattr(employee, "salary", None)
    if salary is None:
        messages.error(request, "La Paie doit d'abord intégrer cet employé au système de paie avant toute augmentation.")
        return redirect("payroll:detail", pk=employee.pk)

    form = SalaryProposalForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        proposed_salary, percentage = form.compute(salary.base_amount)
        proposal = SalaryIncreaseProposal.objects.create(
            employee=employee,
            current_salary=salary.base_amount,
            proposed_salary=proposed_salary,
            increase_type=form.cleaned_data["increase_type"],
            increase_percentage=percentage,
            motif=form.cleaned_data["motif"],
            reason=form.cleaned_data["reason"],
            effective_date=form.cleaned_data["effective_date"],
            proposed_by=request.user,
        )
        _notify_proposal_stage(proposal)
        messages.success(request, "Proposition envoyée à la RH pour validation.")
        return redirect("payroll:proposal_list")

    return render(request, "payroll/proposal_form.html", {"form": form, "employee": employee, "salary": salary})


@login_required
@strict_role_required("MANAGER", "DIRECTION")
def proposal_new(request):
    """Point d'entrée principal : proposer une augmentation en choisissant
    d'abord l'employé. Le Manager est limité à son équipe ; la Direction
    peut proposer pour n'importe quel employé actif. L'Admin n'a pas ce
    droit métier : il ne fait qu'observer le circuit."""
    if request.user.role == "MANAGER":
        queryset = _employee_queryset_for_manager(request.user)
    else:
        queryset = Employee.objects.filter(status=Employee.Status.ACTIVE)
    form = SalaryProposalNewForm(request.POST or None, employee_queryset=queryset)
    if request.method == "POST" and form.is_valid():
        employee = form.cleaned_data["employee"]
        salary = getattr(employee, "salary", None)
        if salary is None:
            messages.error(request, "La Paie doit d'abord intégrer cet employé au système de paie avant toute augmentation.")
            return redirect("payroll:proposal_list")

        proposed_salary, percentage = form.compute(salary.base_amount)
        proposal = SalaryIncreaseProposal.objects.create(
            employee=employee,
            current_salary=salary.base_amount,
            proposed_salary=proposed_salary,
            increase_type=form.cleaned_data["increase_type"],
            increase_percentage=percentage,
            motif=form.cleaned_data["motif"],
            reason=form.cleaned_data["reason"],
            effective_date=form.cleaned_data["effective_date"],
            proposed_by=request.user,
        )
        _notify_proposal_stage(proposal)
        messages.success(request, "Proposition envoyée à la RH pour validation.")
        return redirect("payroll:proposal_list")

    return render(request, "payroll/proposal_new.html", {"form": form})


def _notify_proposal_stage(proposal):
    """Notifie la ou les bonnes personnes selon l'étape courante de la
    proposition. L'Admin n'est volontairement jamais notifié ici : la
    gestion des augmentations n'est pas son rôle métier  — il garde
    uniquement un accès en lecture via la liste des propositions.

    Cas particulier : si c'est la Direction elle-même qui a initié la
    proposition, l'étape « approbation Direction » est redondante — dès
    que la RH valide (budget/politique), on passe directement à APPROVED
    et la Paie est notifiée pour application."""
    employee = proposal.employee
    if proposal.status == SalaryIncreaseProposal.Status.PENDING_RH:
        _notify_users(
            "RH", Notification.Category.SALARY_INCREASE_REQUEST,
            "Nouvelle proposition d'augmentation à valider",
            f"{proposal.proposed_by} propose une augmentation pour {employee} "
            f"({proposal.current_salary} → {proposal.proposed_salary}, {proposal.increase_percentage}%) — motif : {proposal.get_motif_display()}.",
            "/paie/propositions/",
        )
    elif proposal.status == SalaryIncreaseProposal.Status.PENDING_DIRECTION:
        _notify_users(
            "DIRECTION", Notification.Category.SALARY_INCREASE_REQUEST,
            "Proposition d'augmentation à approuver",
            f"La RH a validé une augmentation pour {employee} "
            f"({proposal.current_salary} → {proposal.proposed_salary}, {proposal.increase_percentage}%) — en attente de votre approbation.",
            "/paie/propositions/",
        )
    elif proposal.status == SalaryIncreaseProposal.Status.APPROVED:
        _notify_users(
            "PAYROLL", Notification.Category.SALARY_INCREASE_REQUEST,
            "Augmentation approuvée — à appliquer",
            f"La Direction a approuvé l'augmentation de {employee} "
            f"({proposal.current_salary} → {proposal.proposed_salary}) — à appliquer en paie.",
            "/paie/propositions/",
        )

@login_required
@role_required("MANAGER", "RH", "DIRECTION", "PAYROLL")
def proposal_list(request):
    """Vue unique, adaptée au rôle :
    - Manager : ses propres propositions (tous statuts)
    - RH      : file à valider (PENDING_RH en premier) + historique
    - Direction : file à approuver (PENDING_DIRECTION en premier) + historique
    - Paie    : file à appliquer (APPROVED en premier) + historique
    (l'Admin n'a aucun droit métier sur les augmentations — cap7)"""
    role = request.user.role
    qs = SalaryIncreaseProposal.objects.select_related("employee__user", "proposed_by", "rh_reviewed_by", "approved_by", "applied_by")

    if role == "MANAGER":
        qs = qs.filter(proposed_by=request.user)
        queue_status = None
    elif role == "RH":
        queue_status = SalaryIncreaseProposal.Status.PENDING_RH
    elif role == "DIRECTION":
        queue_status = SalaryIncreaseProposal.Status.PENDING_DIRECTION
    elif role == "PAYROLL":
        queue_status = SalaryIncreaseProposal.Status.APPROVED
    else:
        queue_status = None

    if queue_status:
        # Priorise les éléments à traiter par ce rôle, puis le reste par date.
        pending_ids = set(qs.filter(status=queue_status).values_list("pk", flat=True))
        qs = qs.order_by("-proposed_at")
        proposals = sorted(qs, key=lambda p: (p.pk not in pending_ids,))
    else:
        proposals = qs.order_by("-proposed_at")

    return render(request, "payroll/proposal_list.html", {"proposals": proposals, "role": role})


@login_required
@strict_role_required("RH")
def proposal_rh_validate(request, pk):
    proposal = get_object_or_404(SalaryIncreaseProposal, pk=pk, status=SalaryIncreaseProposal.Status.PENDING_RH)
    form = ProposalValidateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        proposal.rh_reviewed_by = request.user
        proposal.rh_reviewed_at = timezone.now()
        proposal.rh_note = form.cleaned_data["note"]

        proposed_by_role = getattr(proposal.proposed_by, "role", None)
        if proposed_by_role in ("DIRECTION", "ADMIN"):
            # La Direction a elle-même initié la proposition : son
            # approbation est déjà acquise, inutile de la lui redemander.
            proposal.status = SalaryIncreaseProposal.Status.APPROVED
            proposal.approved_by = proposal.proposed_by
            proposal.approval_date = timezone.now()
            success_msg = "Proposition validée et transmise directement à la Paie (initiée par la Direction)."
        else:
            proposal.status = SalaryIncreaseProposal.Status.PENDING_DIRECTION
            success_msg = "Proposition validée et transmise à la Direction."

        proposal.save()
        _notify_proposal_stage(proposal)
        messages.success(request, success_msg)
        return redirect("payroll:proposal_list")
    return render(request, "payroll/proposal_validate.html", {"form": form, "proposal": proposal})


@login_required
@strict_role_required("RH")
def proposal_rh_reject(request, pk):
    proposal = get_object_or_404(SalaryIncreaseProposal, pk=pk, status=SalaryIncreaseProposal.Status.PENDING_RH)
    form = ProposalDecisionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        proposal.rh_reviewed_by = request.user
        proposal.rh_reviewed_at = timezone.now()
        proposal.rh_note = form.cleaned_data["note"]
        proposal.status = SalaryIncreaseProposal.Status.REJECTED
        proposal.save()
        if proposal.proposed_by:
            notify(
                recipient=proposal.proposed_by,
                category=Notification.Category.SALARY_INCREASE_DECIDED,
                title="Proposition d'augmentation rejetée par la RH",
                message=f"La RH a rejeté votre proposition pour {proposal.employee} — motif : {proposal.rh_note}",
                link="/paie/propositions/",
            )
        messages.success(request, "Proposition rejetée, le Manager a été notifié.")
        return redirect("payroll:proposal_list")
    return render(request, "payroll/proposal_decision.html", {"form": form, "proposal": proposal, "stage": "RH", "action": "Rejeter"})


@login_required
@strict_role_required("DIRECTION")
def proposal_direction_approve(request, pk):
    proposal = get_object_or_404(SalaryIncreaseProposal, pk=pk, status=SalaryIncreaseProposal.Status.PENDING_DIRECTION)
    proposal.approved_by = request.user
    proposal.approval_date = timezone.now()
    proposal.status = SalaryIncreaseProposal.Status.APPROVED
    proposal.save()
    _notify_proposal_stage(proposal)
    messages.success(request, "Proposition approuvée et transmise à la Paie pour application.")
    return redirect("payroll:proposal_list")


@login_required
@strict_role_required("DIRECTION")
def proposal_direction_reject(request, pk):
    proposal = get_object_or_404(SalaryIncreaseProposal, pk=pk, status=SalaryIncreaseProposal.Status.PENDING_DIRECTION)
    form = ProposalDecisionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        proposal.approved_by = request.user
        proposal.approval_date = timezone.now()
        proposal.decision_note = form.cleaned_data["note"]
        proposal.status = SalaryIncreaseProposal.Status.REJECTED
        proposal.save()
        for recipient in filter(None, {proposal.proposed_by}):
            notify(
                recipient=recipient,
                category=Notification.Category.SALARY_INCREASE_DECIDED,
                title="Proposition d'augmentation rejetée par la Direction",
                message=f"La Direction a rejeté la proposition pour {proposal.employee} — motif : {proposal.decision_note}",
                link="/paie/propositions/",
            )
        _notify_users(
            "RH", Notification.Category.SALARY_INCREASE_DECIDED,
            "Proposition d'augmentation rejetée par la Direction",
            f"La Direction a rejeté la proposition pour {proposal.employee} — motif : {proposal.decision_note}",
            "/paie/propositions/",
        )
        messages.success(request, "Proposition rejetée, Manager et RH ont été notifiés.")
        return redirect("payroll:proposal_list")
    return render(request, "payroll/proposal_decision.html", {"form": form, "proposal": proposal, "stage": "Direction", "action": "Rejeter"})


@login_required
@strict_role_required("PAYROLL")
def proposal_apply(request, pk):
    """Étape 4 — la Paie applique une augmentation déjà validée par la RH
    et approuvée par la Direction."""
    proposal = get_object_or_404(SalaryIncreaseProposal, pk=pk, status=SalaryIncreaseProposal.Status.APPROVED)
    employee = proposal.employee
    salary, _ = Salary.objects.get_or_create(employee=employee, defaults={"base_amount": 0})

    apply_value = proposal.proposed_salary if proposal.increase_type == SalaryHistory.IncreaseType.FIXED else proposal.increase_percentage
    history = _apply_increase(
        employee, salary, proposal.increase_type, apply_value,
        proposal.effective_date, proposal.reason,
        request.user, decided_label=(
            f"Manager : {proposal.proposed_by} · RH : {proposal.rh_reviewed_by} · Direction : {proposal.approved_by}"
        ),
    )
    proposal.status = SalaryIncreaseProposal.Status.APPLIED
    proposal.applied_by = request.user
    proposal.applied_at = timezone.now()
    proposal.resulting_history = history
    proposal.save()

    for recipient in filter(None, {proposal.proposed_by, proposal.approved_by}):
        notify(
            recipient=recipient,
            category=Notification.Category.SALARY_INCREASE_DECIDED,
            title="Augmentation appliquée",
            message=f"L'augmentation de {employee} a été appliquée par la Paie ({proposal.current_salary} → {proposal.proposed_salary}).",
            link=f"/paie/{employee.pk}/",
        )
    # L'employé concerné doit lui-même être informé de l'augmentation de son salaire.
    notify(
        recipient=employee.user,
        category=Notification.Category.SALARY_UPDATE,
        title="Votre salaire a été augmenté",
        message=(
            f"Votre salaire de base passe de {proposal.current_salary} à {proposal.proposed_salary}, "
            f"effectif à partir du {proposal.effective_date}."
        ),
        link=f"/paie/{employee.pk}/",
    )
    messages.success(request, "Augmentation appliquée et historisée.")
    return redirect("payroll:proposal_list")


@login_required
@role_required("PAYROLL", "RH", "DIRECTION")
def payroll_overview(request):
    """Tableau de bord Paie : masse salariale + état de préparation du
    mois en cours (préparée/validée/en attente)."""
    salaries = Salary.objects.select_related("employee")
    total_mass = sum(s.total for s in salaries)

    today = timezone.localdate()
    nb_employes = Employee.objects.filter(status=Employee.Status.ACTIVE).count()
    payslips_month = PayslipRecord.objects.filter(month=today.month, year=today.year)
    nb_preparees = payslips_month.count()
    nb_validees = payslips_month.filter(status=PayslipRecord.Status.VALIDATED).count()
    nb_en_attente = max(nb_employes - nb_preparees, 0)
    total_retenues = sum(p.deductions_amount for p in payslips_month)
    net_a_payer = sum(p.net_amount for p in payslips_month)
    nb_proposals_pending = SalaryIncreaseProposal.objects.exclude(
        status__in=[SalaryIncreaseProposal.Status.REJECTED, SalaryIncreaseProposal.Status.APPLIED]
    ).count()

    return render(request, "payroll/overview.html", {
        "salaries": salaries, "total_mass": total_mass, "today": today,
        "nb_employes": nb_employes, "nb_preparees": nb_preparees,
        "nb_validees": nb_validees, "nb_en_attente": nb_en_attente,
        "total_retenues": total_retenues, "net_a_payer": net_a_payer,
        "nb_proposals_pending": nb_proposals_pending,
    })


@login_required
@strict_role_required("PAYROLL")
def payslip_validate(request, pk):
    """Valide (clôture) définitivement le bulletin de paie du mois.

    Verrou de clôture ("payroll lock", pratique standard des logiciels de
    paie) : on REFUSE la validation tant qu'il reste, pour ce salarié et ce
    mois, des congés ou autorisations APPROUVÉS mais pas encore marqués
    « Traité » dans la file d'attente Paie. Objectif : s'assurer que la
    Paie a bien passé en revue tous les éléments du mois avant de figer
    définitivement le bulletin — sans pour autant bloquer le calcul
    automatique au jour le jour (qui, lui, reste basé sur le statut
    APPROVED, pour éviter tout risque de sur-paiement en cas d'oubli)."""
    record = get_object_or_404(PayslipRecord, pk=pk)
    employee = record.employee

    nb_conges, nb_autorisations = _pending_payroll_items(employee, record.month, record.year)

    if nb_conges or nb_autorisations:
        messages.error(
            request,
            f"Impossible de valider le bulletin de {employee} ({record.month:02d}/{record.year}) : "
            f"{nb_conges} congé(s) et {nb_autorisations} autorisation(s) approuvés restent « À traiter » "
            f"sur ce mois. Traitez-les d'abord depuis la file d'attente Paie."
        )
        return redirect("payroll:queue")

    record.status = PayslipRecord.Status.VALIDATED
    record.validated_by = request.user
    record.validated_at = timezone.now()
    record.save()
    messages.success(request, "Bulletin de paie validé.")
    return redirect("payroll:detail", pk=record.employee.pk)

@login_required
@role_required("PAYROLL", "RH", "EMPLOYEE", "ADMIN", "DIRECTION")
def payslip_export(request, pk):
    """Génère, historise (PayslipRecord) et télécharge le bulletin de paie
    au format PDF, pour le MOIS SAISI par la personne (paramètres GET
    `month`/`year`, mois en cours par défaut). Un Employé (ou un Admin, qui
    n'a aucun droit métier sur la paie d'autrui) ne peut télécharger que
    son propre bulletin, et jamais un mois futur."""
    employee = get_object_or_404(Employee, pk=pk)
    if request.user.role in ("EMPLOYEE", "ADMIN"):
        employee_profile = getattr(request.user, "employee_profile", None)
        if employee.pk != getattr(employee_profile, "pk", None):
            return HttpResponseForbidden("Vous ne pouvez télécharger que votre propre bulletin de paie.")
    salary, _ = Salary.objects.get_or_create(employee=employee, defaults={"base_amount": 0})

    today = timezone.localdate()
    mois, annee = _parse_month_year(request, today)
    if (annee, mois) > (today.year, today.month):
        messages.error(request, "Impossible de générer le bulletin d'un mois futur.")
        return redirect("payroll:detail", pk=employee.pk)

    existing = PayslipRecord.objects.filter(employee=employee, month=mois, year=annee).first()

    dernier_jour_mois = calendar.monthrange(annee, mois)[1]
    fin_mois = date(annee, mois, dernier_jour_mois)
    mois_termine = fin_mois < today
    est_valide = bool(existing and existing.status == PayslipRecord.Status.VALIDATED)

    # pour télécharger un bulletin, il faut TOUJOURS que le
    # mois soit terminé ET que le bulletin ait été validé par la Paie —
    # sauf pour la Paie elle-même, qui doit pouvoir préparer/consulter un
    # brouillon (non encore validé) une fois le mois fini, le temps de le
    # vérifier avant de le valider (elle ne peut de toute façon jamais le
    # valider avant la fin du mois, voir payslip_validate).
    if request.user.role == "PAYROLL":
        if not mois_termine and not est_valide:
            messages.error(
                request,
                f"Le mois {mois:02d}/{annee} n'est pas encore terminé : vous pouvez le consulter (« Afficher »), "
                f"mais le bulletin ne pourra être préparé/téléchargé qu'à partir du "
                f"{(fin_mois + timedelta(days=1)).strftime('%d/%m/%Y')}."
            )
            return redirect("payroll:detail", pk=employee.pk)
    else:
        if not est_valide:
            if not mois_termine:
                messages.error(
                    request,
                    f"Le bulletin de {mois:02d}/{annee} n'est pas encore disponible : le mois n'est pas terminé."
                )
            else:
                messages.error(
                    request,
                    f"Le bulletin de {mois:02d}/{annee} n'a pas encore été validé par la Paie — "
                    f"il ne peut pas encore être téléchargé."
                )
            return redirect("payroll:detail", pk=employee.pk)

    payslip = build_payslip(salary, month=mois, year=annee, notify_overtime_alerts=(mois, annee) == (today.month, today.year))
    
    if payslip["hors_contrat"] and not (existing and existing.status == PayslipRecord.Status.VALIDATED):
        # Aucun contrat de cet employé ne couvre ce mois (avant l'embauche,
        # ou trou entre deux contrats) : on refuse de générer un bulletin
        # fabriqué à partir du salaire actuel — ça reviendrait à créer un
        # bulletin de paie pour un mois où l'employé n'était pas employé.
        messages.error(
            request,
            f"Impossible de générer un bulletin pour {payslip['mois_annee']} : "
            f"{employee} n'avait aucun contrat actif ce mois-ci."
        )
        return redirect("payroll:detail", pk=employee.pk)

    if existing and existing.status == PayslipRecord.Status.VALIDATED:
        # Un bulletin déjà validé est un historique figé  : on ne réécrit
        # jamais ses valeurs enregistrées, même si on regénère le PDF.
        messages.info(request, "Ce bulletin a déjà été validé : les valeurs historisées ne sont pas modifiées.")
    else:
        PayslipRecord.objects.update_or_create(
            employee=employee, month=mois, year=annee,
            defaults={
                "gross_amount": payslip["salaire_brut"],
                "deductions_amount": payslip["total_retenues"],
                "net_amount": payslip["salaire_net"],
                "generated_by": request.user,
                # Snapshot figé  : ces valeurs ne sont plus jamais recalculées
                # après coup, même si le contrat ou la politique de paie changent.
                "base_salary_used": payslip["salaire_base"],
                "hourly_rate_used": payslip["taux_horaire"],
                "expected_hours_used": payslip["heures_prevues"],
                "worked_hours_used": payslip["heures_travaillees"],
                "overtime_hours_used": payslip["heures_sup"],
                "overtime_amount_used": payslip["montant_heures_sup"],
                "absence_deduction_used": payslip["retenue_absences"],
            },
        )

    pdf_bytes = render_payslip_pdf(payslip)
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    filename = f"bulletin_paie_{employee.matricule}_{mois:02d}_{annee}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _parse_month_year(request, today):
    """Lit `month`/`year` depuis la requête GET (recherche par mois saisi
    par l'utilisateur) ; retombe sur le mois en cours si absent/invalide."""
    try:
        mois = int(request.GET.get("month", today.month))
        annee = int(request.GET.get("year", today.year))
        if not (1 <= mois <= 12):
            raise ValueError
    except (TypeError, ValueError):
        mois, annee = today.month, today.year
    return mois, annee


# ---------------------------------------------------------------------
# Barème de paie (CNSS/CSS/IRPP) — donnée MÉTIER de la Paie 
# ---------------------------------------------------------------------
# La Paie est seule habilitée à modifier les taux : c'est elle qui reçoit
# l'info de la Loi de Finances et l'applique dans les bulletins. RH et
# Direction consultent en lecture seule (politique salariale / budget).
# Admin n'a aucun droit ici, ni en lecture ni en écriture — la Paie est un
# domaine métier qui ne le concerne pas.

@login_required
@role_required("PAYROLL", "RH", "DIRECTION")
def payroll_rates_list(request):
    """Consultation du barème actuellement en vigueur + historique complet.
    Lecture seule pour RH/Direction ; la Paie y trouve en plus le bouton
    pour ajouter un nouveau barème."""
    rate_sets = PayrollRateSet.objects.prefetch_related("brackets", "created_by")
    active = PayrollRateSet.active_for()
    return render(request, "payroll/rates_list.html", {"rate_sets": rate_sets, "active": active})


@login_required
@strict_role_required("PAYROLL")
def payroll_rate_create(request):
    """Création d'un nouveau barème (nouvelle date d'effet) — réservé à la
    Paie. RH/Direction/Admin ne peuvent pas accéder à cette page, même en
    tant que superutilisateur (strict_role_required, pas role_required)."""
    form = PayrollRateSetForm(request.POST or None)
    formset = PayrollRateBracketFormSet(request.POST or None, instance=form.instance)

    if request.method == "POST" and form.is_valid():
        rate_set = form.save(commit=False)
        rate_set.created_by = request.user
        rate_set.save()
        formset = PayrollRateBracketFormSet(request.POST, instance=rate_set)
        if formset.is_valid():
            formset.save()
            messages.success(request, f"Nouveau barème enregistré, en vigueur à partir du {rate_set.effective_date}.")
            return redirect("payroll:rates_list")
        else:
            rate_set.delete()  # on annule si les tranches IRPP ne sont pas valides

    return render(request, "payroll/rate_form.html", {"form": form, "formset": formset})


# ----------------------------------------------------------------------
# Politique de paie (heures sup., taux horaire, jour de repos, limite interne)
# et jours fériés — distincts du barème CNSS/CSS/IRPP ci-dessus.
# ----------------------------------------------------------------------

@login_required
@role_required("PAYROLL", "RH", "DIRECTION")
def payroll_policy_view(request):
    """Consultation de la politique de paie en vigueur. Lecture seule pour
    RH/Direction ; la Paie y trouve en plus le bouton de modification."""
    policy = PayrollPolicy.get_solo()
    holidays = PublicHoliday.objects.all()
    return render(request, "payroll/policy_view.html", {"policy": policy, "holidays": holidays})


@login_required
@strict_role_required("PAYROLL")
def payroll_policy_edit(request):
    """Modification de la politique de paie — réservé à la Paie, comme pour
    le barème CNSS/CSS/IRPP (Admin en lecture seule, jamais en modification)."""
    policy = PayrollPolicy.get_solo()
    form = PayrollPolicyForm(request.POST or None, instance=policy)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Politique de paie mise à jour.")
        return redirect("payroll:policy_view")
    return render(request, "payroll/policy_form.html", {"form": form})


@login_required
@strict_role_required("PAYROLL")
def public_holiday_create(request):
    """Ajout d'un jour férié — réservé à la Paie."""
    form = PublicHolidayForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Jour férié enregistré.")
        return redirect("payroll:policy_view")
    return render(request, "payroll/public_holiday_form.html", {"form": form})