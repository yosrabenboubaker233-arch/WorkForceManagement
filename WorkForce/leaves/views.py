from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone

from accounts.decorators import role_required
from accounts.models import User
from .models import LeaveRequest, Authorization, LeaveBalanceTransaction, PayrollTreatment
from .forms import LeaveRequestForm, DecisionForm, AuthorizationForm, AuthorizationTreatmentForm
from notifications.models import Notification
from notifications.emailing import notify


def _apply_leave_balance_deduction(leave):
    """Décrémente le solde de congé annuel UNIQUEMENT si le type de congé
    est configuré pour ça (`LeaveType.reduces_annual_balance`) — l'impact
    paie (`treatment`) et l'impact sur le solde annuel sont deux questions
    indépendantes (§1). Trace le mouvement (§5)."""
    if not leave.leave_type.reduces_annual_balance:
        return
    employee = leave.employee
    before = employee.leave_balance_days
    employee.leave_balance_days -= Decimal(leave.nb_days)
    employee.save(update_fields=["leave_balance_days"])
    LeaveBalanceTransaction.objects.create(
        employee=employee, source=LeaveBalanceTransaction.Source.LEAVE_REQUEST,
        leave_request=leave, days_converted=Decimal(leave.nb_days),
        balance_before=before, balance_after=employee.leave_balance_days,
        note=f"Congé {leave.leave_type} du {leave.start_date} au {leave.end_date}",
    )


def _convert_authorization_hours_to_leave(authorization):
    """Cumule les heures de l'autorisation approuvée, convertit chaque
    tranche de `hours_per_day` (contrat en vigueur à la date de
    l'autorisation) en 1 jour déduit du solde annuel, conserve le reste en
    report (§3, §4), trace le mouvement (§5), et force `treatment` à
    NO_DEDUCTION pour éviter toute double déduction sur ces heures (§6).
    N'utilise jamais un « 8h = 1 jour » codé en dur."""
    from payroll.contract_utils import get_contract_on

    employee = authorization.employee
    contract = get_contract_on(employee, authorization.date)
    if contract is None or not contract.hours_per_day:
        return  # aucune règle contractuelle applicable : rien à convertir

    hours_per_day = Decimal(contract.hours_per_day)
    cumul = employee.authorization_hours_carry + authorization.duration_hours

    jours_convertis = (cumul // hours_per_day)  # Decimal, division entière
    heures_restantes = cumul - (jours_convertis * hours_per_day)

    employee.authorization_hours_carry = heures_restantes

    if jours_convertis > 0:
        before = employee.leave_balance_days
        employee.leave_balance_days -= jours_convertis
        employee.save(update_fields=["leave_balance_days", "authorization_hours_carry"])
        LeaveBalanceTransaction.objects.create(
            employee=employee, source=LeaveBalanceTransaction.Source.AUTHORIZATION,
            authorization=authorization, hours_consumed=authorization.duration_hours,
            days_converted=jours_convertis, balance_before=before, balance_after=employee.leave_balance_days,
            note=f"Cumul {cumul}h / {hours_per_day}h par jour -> {jours_convertis} j, reste {heures_restantes}h",
        )
    else:
        employee.save(update_fields=["authorization_hours_carry"])

    # Ces heures sont désormais couvertes par le solde de congé (converties
    # ou en report) : jamais de déduction de salaire pour elles (§6).
    if authorization.treatment != PayrollTreatment.NO_DEDUCTION:
        authorization.treatment = PayrollTreatment.NO_DEDUCTION
        authorization.save(update_fields=["treatment"])


# =====================================================================
# Notifications communes au workflow (congés ET autorisations)
# =====================================================================

def _notify_step1(obj, kind_label, detail, url):
    for user in obj.step1_recipients():
        notify(
            recipient=user,
            category=Notification.Category.LEAVE_NEW if kind_label == "congé" else Notification.Category.AUTH_NEW,
            title=f"Nouvelle demande de {kind_label} à valider",
            message=f"{obj.employee} — {detail}",
            link=url,
        )


def _notify_requester(obj, title, message, url):
    is_auth = hasattr(obj, "start_time")  # Authorization a start_time/end_time, LeaveRequest non
    if "refus" in title.lower():
        category = Notification.Category.AUTH_REJECTED if is_auth else Notification.Category.LEAVE_REJECTED
    else:
        category = Notification.Category.AUTH_APPROVED if is_auth else Notification.Category.LEAVE_APPROVED
    notify(recipient=obj.employee.user, category=category, title=title, message=message, link=url)


def _notify_step2(obj, kind_label, detail, url):
    for user in obj.step2_recipients():
        notify(
            recipient=user,
            category=Notification.Category.LEAVE_NEW if kind_label == "congé" else Notification.Category.AUTH_NEW,
            title=f"Demande de {kind_label} à valider (RH)",
            message=f"{obj.employee} — {detail} — déjà approuvée en étape 1 par {obj.step1_decided_by}.",
            link=url,
        )


def _notify_payroll(obj, kind_label, detail):
    for user in obj.payroll_recipients():
        notify(
            recipient=user,
            category=Notification.Category.SALARY_UPDATE,
            title=f"{kind_label.capitalize()} approuvé(e) — à traiter en paie",
            message=f"{obj.employee} — {detail} — statut Paie : à traiter.",
            link="/paie/file-attente/",
        )


# =====================================================================
# CONGÉS
# =====================================================================

@login_required
def leave_request_create(request):
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        messages.error(request, "Aucun dossier employé associé à ce compte.")
        return redirect("accounts:dashboard")
    if request.user.role == "DIRECTION":
        messages.info(request, "La Direction Générale ne soumet pas de demande de congé.")
        return redirect("accounts:dashboard")

    form = LeaveRequestForm(request.POST or None, request.FILES or None, employee=employee)
    if request.method == "POST" and form.is_valid():
        leave = form.save(commit=False)
        leave.employee = employee
        leave.init_workflow()
        leave.save()

        detail = f"du {leave.start_date} au {leave.end_date} ({leave.leave_type})"
        _notify_step1(leave, "congé", detail, "/conges/a-valider/")

        messages.success(
            request,
            f"Votre demande a été envoyée pour validation (étape 1 : {leave.step1_label}) — "
            f"notification application + email."
        )
        return redirect("leaves:my_requests")

    return render(request, "leaves/leave_request_form.html", {"form": form, "employee": employee})


@login_required
def my_requests(request):
    employee = getattr(request.user, "employee_profile", None)
    leaves = LeaveRequest.objects.filter(employee=employee).order_by("-created_at") if employee else []
    return render(request, "leaves/my_requests.html", {"leaves": leaves, "employee": employee})


@login_required
def leave_cancel(request, pk):
    leave = get_object_or_404(LeaveRequest, pk=pk)
    if leave.employee.user != request.user:
        messages.error(request, "Action non autorisée.")
        return redirect("leaves:my_requests")
    if leave.status == LeaveRequest.Status.PENDING_STEP1:
        leave.status = LeaveRequest.Status.CANCELLED
        leave.save()
        messages.success(request, "Demande annulée.")
    return redirect("leaves:my_requests")


@login_required
def leave_edit(request, pk):
    """L'employé ne peut modifier sa demande QUE tant qu'elle n'a encore
    été traitée par personne (étape 1 toujours en attente)."""
    leave = get_object_or_404(LeaveRequest, pk=pk)
    if leave.employee.user != request.user:
        messages.error(request, "Action non autorisée.")
        return redirect("leaves:my_requests")
    if leave.status != LeaveRequest.Status.PENDING_STEP1:
        messages.error(request, "Cette demande a déjà été traitée, elle ne peut plus être modifiée.")
        return redirect("leaves:my_requests")

    form = LeaveRequestForm(request.POST or None, request.FILES or None, instance=leave, employee=leave.employee)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Demande de congé modifiée.")
        return redirect("leaves:my_requests")
    return render(request, "leaves/leave_request_form.html", {"form": form, "employee": leave.employee, "editing": True})


@login_required
def leave_delete(request, pk):
    """Suppression définitive — uniquement tant que la demande est encore
    en attente d'étape 1 (aucune décision prise)."""
    leave = get_object_or_404(LeaveRequest, pk=pk)
    if leave.employee.user != request.user:
        messages.error(request, "Action non autorisée.")
        return redirect("leaves:my_requests")
    if leave.status != LeaveRequest.Status.PENDING_STEP1:
        messages.error(request, "Cette demande a déjà été traitée, elle ne peut plus être supprimée.")
        return redirect("leaves:my_requests")
    leave.delete()
    messages.success(request, "Demande de congé supprimée.")
    return redirect("leaves:my_requests")


def _auto_expire(items):
    """Marque automatiquement comme EXPIRÉE toute demande en attente dont la
    date est déjà passée, et ne retourne que celles encore décidables.
    Appelé à chaque affichage de la boîte de validation : une demande dont
    la date est passée sans décision ne doit plus pouvoir être acceptée ni
    refusée (elle n'a plus de sens rétroactivement)."""
    encore_valides = []
    for item in items:
        if item.is_expired:
            item.mark_expired()
        else:
            encore_valides.append(item)
    return encore_valides


@login_required
@role_required("MANAGER", "RH", "DIRECTION")
def validation_inbox(request):
    """Boîte de validation, contextuelle au rôle connecté :
    - Manager / Direction : demandes en attente d'étape 1 qui leur reviennent
    - RH : demandes en attente d'étape 2 (validation RH)
    """
    user = request.user
    step1_leaves, step1_auths = [], []
    step2_leaves, step2_auths = [], []

    if user.role in ("MANAGER", "DIRECTION"):
        pending_leaves = _auto_expire(LeaveRequest.objects.filter(status=LeaveRequest.Status.PENDING_STEP1))
        pending_auths = _auto_expire(Authorization.objects.filter(status=Authorization.Status.PENDING_STEP1))
        if user.role == "MANAGER":
            manager_profile = getattr(user, "employee_profile", None)
            step1_leaves = [l for l in pending_leaves if l.step1_role == "MANAGER" and l.employee.manager_id == getattr(manager_profile, "id", None)]
            step1_auths = [a for a in pending_auths if a.step1_role == "MANAGER" and a.employee.manager_id == getattr(manager_profile, "id", None)]
        else:  # DIRECTION
            step1_leaves = [l for l in pending_leaves if l.step1_role == "DIRECTION"]
            step1_auths = [a for a in pending_auths if a.step1_role == "DIRECTION"]

    if user.role == "RH":
        step2_leaves = _auto_expire(LeaveRequest.objects.filter(status=LeaveRequest.Status.PENDING_STEP2))
        step2_auths = _auto_expire(Authorization.objects.filter(status=Authorization.Status.PENDING_STEP2))

    return render(request, "leaves/validation_inbox.html", {
        "step1_leaves": step1_leaves, "step1_auths": step1_auths,
        "step2_leaves": step2_leaves, "step2_auths": step2_auths,
    })


def _guard_step1_access(request, obj):
    """Vérifie que l'utilisateur connecté est bien légitime pour statuer sur l'étape 1."""
    user = request.user
    if obj.step1_role == "MANAGER":
        manager_profile = getattr(user, "employee_profile", None)
        return obj.employee.manager_id == getattr(manager_profile, "id", None)
    return user.role == "DIRECTION"


@login_required
@role_required("MANAGER", "RH", "DIRECTION")
def leave_decide_step1(request, pk, decision):
    leave = get_object_or_404(LeaveRequest, pk=pk)
    if leave.status != LeaveRequest.Status.PENDING_STEP1 or not _guard_step1_access(request, leave):
        messages.error(request, "Cette demande n'est pas (ou plus) en attente de votre validation.")
        return redirect("leaves:validation_inbox")
    if leave.is_expired:
        leave.mark_expired()
        messages.error(request, "Cette demande a expiré (sa date est passée) : elle ne peut plus être acceptée ni refusée.")
        return redirect("leaves:validation_inbox")
    
    form = DecisionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        comment = form.cleaned_data["comment"].strip()
        if decision == "reject" and not comment:
            messages.error(request, "Un motif de refus est obligatoire.")
        else:
            approved = decision == "approve"
            leave.apply_step1_decision(approved, request.user, comment)

            detail = f"du {leave.start_date} au {leave.end_date} ({leave.leave_type})"
            if not approved:
                _notify_requester(leave, "Congé refusé", f"Votre demande {detail} a été refusée par {leave.step1_label}. Motif : {comment}", "/conges/mes-demandes/")
            elif leave.step2_required:
                _notify_step2(leave, "congé", detail, "/conges/a-valider/")
                _notify_requester(leave, "Congé approuvé (étape 1)", f"Votre demande {detail} a été approuvée par {leave.step1_label} et transmise à la RH pour validation finale.", "/conges/mes-demandes/")
            else:
                _apply_leave_balance_deduction(leave)
                _notify_requester(leave, "Congé approuvé", f"Votre demande {detail} a été définitivement approuvée.", "/conges/mes-demandes/")
                _notify_payroll(leave, "congé", detail)

            messages.success(request, "Décision enregistrée (notification application + email envoyée).")
            return redirect("leaves:validation_inbox")

    return render(request, "leaves/leave_decide.html", {"leave": leave, "form": form, "decision": decision, "step": 1})


@login_required
@role_required("RH")
def leave_decide_step2(request, pk, decision):
    leave = get_object_or_404(LeaveRequest, pk=pk)
    if leave.status != LeaveRequest.Status.PENDING_STEP2:
        messages.error(request, "Cette demande n'est pas (ou plus) en attente de validation RH.")
        return redirect("leaves:validation_inbox")
    if leave.is_expired:
        leave.mark_expired()
        messages.error(request, "Cette demande a expiré (sa date est passée) : elle ne peut plus être acceptée ni refusée.")
        return redirect("leaves:validation_inbox")
    
    form = DecisionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        comment = form.cleaned_data["comment"].strip()
        if decision == "reject" and not comment:
            messages.error(request, "Un motif de refus est obligatoire.")
        else:
            approved = decision == "approve"
            leave.apply_step2_decision(approved, request.user, comment)

            detail = f"du {leave.start_date} au {leave.end_date} ({leave.leave_type})"
            if approved:
                _apply_leave_balance_deduction(leave)
                _notify_requester(leave, "Congé approuvé", f"Votre demande {detail} a été définitivement approuvée par la RH.", "/conges/mes-demandes/")
                _notify_payroll(leave, "congé", detail)
            else:
                _notify_requester(leave, "Congé refusé (RH)", f"Votre demande {detail}, pourtant approuvée en étape 1, a été refusée par la RH. Motif : {comment}", "/conges/mes-demandes/")

            messages.success(request, "Décision RH enregistrée (notification application + email envoyée).")
            return redirect("leaves:validation_inbox")

    return render(request, "leaves/leave_decide.html", {"leave": leave, "form": form, "decision": decision, "step": 2})


@login_required
@role_required("RH", "ADMIN")
def leave_history(request):
    leaves = LeaveRequest.objects.select_related("employee__user").order_by("-created_at")
    return render(request, "leaves/leave_history.html", {"leaves": leaves})


# =====================================================================
# AUTORISATIONS D'ABSENCE
# =====================================================================

@login_required
def authorization_create(request):
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        messages.error(request, "Aucun dossier employé associé à ce compte.")
        return redirect("accounts:dashboard")
    if request.user.role == "DIRECTION":
        messages.info(request, "La Direction Générale ne soumet pas de demande d'autorisation.")
        return redirect("accounts:dashboard")

    form = AuthorizationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        auth = form.save(commit=False)
        auth.employee = employee
        auth.init_workflow()
        auth.save()

        detail = f"{auth.get_kind_display()} — le {auth.date} de {auth.start_time.strftime('%H:%M')} à {auth.end_time.strftime('%H:%M')} ({auth.duration_hours} h) — motif : {auth.reason}"
        _notify_step1(auth, "autorisation", detail, "/conges/a-valider/")

        messages.success(
            request,
            f"Votre demande a été envoyée pour validation (étape 1 : {auth.step1_label}) — notification application + email."
        )
        return redirect("leaves:my_authorizations")

    return render(request, "leaves/authorization_form.html", {"form": form, "employee": employee})


@login_required
def my_authorizations(request):
    employee = getattr(request.user, "employee_profile", None)
    authorizations = Authorization.objects.filter(employee=employee).order_by("-date") if employee else []
    cumul_mois = 0
    if employee:
        today = timezone.localdate()
        cumul_mois = sum(
            a.duration_hours for a in Authorization.objects.filter(
                employee=employee, status=Authorization.Status.APPROVED,
                date__year=today.year, date__month=today.month,
            )
        )
    return render(request, "leaves/my_authorizations.html", {
        "authorizations": authorizations, "employee": employee, "cumul_mois": cumul_mois,
    })


@login_required
def authorization_edit(request, pk):
    auth = get_object_or_404(Authorization, pk=pk)
    if auth.employee.user != request.user:
        messages.error(request, "Action non autorisée.")
        return redirect("leaves:my_authorizations")
    if auth.status != Authorization.Status.PENDING_STEP1:
        messages.error(request, "Cette demande a déjà été traitée, elle ne peut plus être modifiée.")
        return redirect("leaves:my_authorizations")

    form = AuthorizationForm(request.POST or None, instance=auth)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Demande d'autorisation modifiée.")
        return redirect("leaves:my_authorizations")
    return render(request, "leaves/authorization_form.html", {"form": form, "employee": auth.employee, "editing": True})


@login_required
def authorization_delete(request, pk):
    auth = get_object_or_404(Authorization, pk=pk)
    if auth.employee.user != request.user:
        messages.error(request, "Action non autorisée.")
        return redirect("leaves:my_authorizations")
    if auth.status != Authorization.Status.PENDING_STEP1:
        messages.error(request, "Cette demande a déjà été traitée, elle ne peut plus être supprimée.")
        return redirect("leaves:my_authorizations")
    auth.delete()
    messages.success(request, "Demande d'autorisation supprimée.")
    return redirect("leaves:my_authorizations")


@login_required
@role_required("MANAGER", "RH", "DIRECTION")
def authorization_decide_step1(request, pk, decision):
    auth = get_object_or_404(Authorization, pk=pk)
    if auth.status != Authorization.Status.PENDING_STEP1 or not _guard_step1_access(request, auth):
        messages.error(request, "Cette demande n'est pas (ou plus) en attente de votre validation.")
        return redirect("leaves:validation_inbox")
    if auth.is_expired:
        auth.mark_expired()
        messages.error(request, "Cette demande a expiré (sa date est passée) : elle ne peut plus être acceptée ni refusée.")
        return redirect("leaves:validation_inbox")
    
    form = DecisionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        comment = form.cleaned_data["comment"].strip()
        if decision == "reject" and not comment:
            messages.error(request, "Un motif de refus est obligatoire.")
        else:
            approved = decision == "approve"
            auth.apply_step1_decision(approved, request.user, comment)

            detail = f"{auth.get_kind_display()} — le {auth.date} ({auth.start_time.strftime('%H:%M')}-{auth.end_time.strftime('%H:%M')})"
            if not approved:
                _notify_requester(auth, "Autorisation refusée", f"Votre demande {detail} a été refusée par {auth.step1_label}. Motif : {comment}", "/conges/autorisations/mes-demandes/")
            elif auth.step2_required:
                _notify_step2(auth, "autorisation", detail, "/conges/a-valider/")
                _notify_requester(auth, "Autorisation approuvée (étape 1)", f"Votre demande {detail} a été approuvée par {auth.step1_label} et transmise à la RH.", "/conges/autorisations/mes-demandes/")
            else:
                _convert_authorization_hours_to_leave(auth)
                _notify_requester(auth, "Autorisation approuvée", f"Votre demande {detail} a été définitivement approuvée.", "/conges/autorisations/mes-demandes/")
                _notify_payroll(auth, "autorisation", detail)

            messages.success(request, "Décision enregistrée (notification application + email envoyée).")
            return redirect("leaves:validation_inbox")

    return render(request, "leaves/authorization_decide.html", {"auth": auth, "form": form, "decision": decision, "step": 1})


@login_required
@role_required("RH")
def authorization_decide_step2(request, pk, decision):
    auth = get_object_or_404(Authorization, pk=pk)
    if auth.status != Authorization.Status.PENDING_STEP2:
        messages.error(request, "Cette demande n'est pas (ou plus) en attente de validation RH.")
        return redirect("leaves:validation_inbox")
    if auth.is_expired:
        auth.mark_expired()
        messages.error(request, "Cette demande a expiré (sa date est passée) : elle ne peut plus être acceptée ni refusée.")
        return redirect("leaves:validation_inbox")
    
    form = DecisionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        comment = form.cleaned_data["comment"].strip()
        if decision == "reject" and not comment:
            messages.error(request, "Un motif de refus est obligatoire.")
        else:
            approved = decision == "approve"
            auth.apply_step2_decision(approved, request.user, comment)

            detail = f"{auth.get_kind_display()} — le {auth.date} ({auth.start_time.strftime('%H:%M')}-{auth.end_time.strftime('%H:%M')})"
            if approved:
                _convert_authorization_hours_to_leave(auth)
                _notify_requester(auth, "Autorisation approuvée", f"Votre demande {detail} a été définitivement approuvée par la RH.", "/conges/autorisations/mes-demandes/")
                _notify_payroll(auth, "autorisation", detail)
            else:
                _notify_requester(auth, "Autorisation refusée (RH)", f"Votre demande {detail}, pourtant approuvée en étape 1, a été refusée par la RH. Motif : {comment}", "/conges/autorisations/mes-demandes/")

            messages.success(request, "Décision RH enregistrée (notification application + email envoyée).")
            return redirect("leaves:validation_inbox")

    return render(request, "leaves/authorization_decide.html", {"auth": auth, "form": form, "decision": decision, "step": 2})


@login_required
@role_required("RH", "ADMIN", "PAYROLL")
def authorization_history(request):
    authorizations = Authorization.objects.select_related("employee__user").order_by("-date")
    return render(request, "leaves/authorization_history.html", {"authorizations": authorizations})


@login_required
@role_required("RH", "ADMIN", "PAYROLL")
def authorization_set_treatment(request, pk):
    """Permet à la RH/Paie d'ajuster le traitement paie d'une autorisation
    déjà approuvée (§7 : ex. requalifier une autorisation en heures à
    récupérer). Ne modifie ni le statut ni les autres champs de la demande."""
    auth = get_object_or_404(Authorization, pk=pk)
    form = AuthorizationTreatmentForm(request.POST or None, instance=auth)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Traitement paie de l'autorisation mis à jour.")
        return redirect("leaves:authorization_history")
    return render(request, "leaves/authorization_treatment_form.html", {"form": form, "auth": auth})