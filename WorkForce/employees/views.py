from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Q
from django.contrib import messages

from accounts.decorators import role_required
from .models import Employee, Document, WorkHistoryEntry, Department, Contract
from .forms import EmployeeForm, EmployeeCreationForm, DocumentForm, WorkHistoryForm, MyProfileForm, ContractForm, ContractEndForm
from accounts.models import User
from accounts.utils import generate_username, generate_temporary_password
from notifications.emailing import send_welcome_email, notify
from notifications.models import Notification

@login_required
@role_required("RH", "ADMIN", "MANAGER", "DIRECTION", "PAYROLL")
def employee_list(request):
    query = request.GET.get("q", "")
    department_id = request.GET.get("department", "")
    employees = Employee.objects.select_related("user", "department", "manager__user")

    if request.user.role == "MANAGER":
        manager_profile = getattr(request.user, "employee_profile", None)
        employees = employees.filter(manager=manager_profile)

    if query:
        employees = employees.filter(
            Q(user__first_name__icontains=query)
            | Q(user__last_name__icontains=query)
            | Q(job_title__icontains=query)
        )
    if department_id:
        employees = employees.filter(department_id=department_id)

    context = {
        "employees": employees,
        "departments": Department.objects.all(),
        "query": query,
        "department_id": department_id,
    }
    return render(request, "employees/employee_list.html", context)

@login_required
def employee_detail(request, pk):
    employee = get_object_or_404(Employee.objects.select_related("user", "department", "manager__user"), pk=pk)

    # Un employé ne peut voir que sa propre fiche, sauf RH/Manager/Admin
    if request.user.role == "EMPLOYEE" and employee.user != request.user:
        messages.error(request, "Accès refusé à ce dossier.")
        return redirect("accounts:dashboard")

    context = {
        "employee": employee,
        "documents": employee.documents.all(),
        "history": employee.history.all(),
        "team": employee.team_members.all(),
        # Référence pratique : moyenne mensuelle dérivée des heures/semaine
        # (52 semaines / 12 mois), affichée à titre indicatif à côté de
        # "Heures / semaine" pour éviter la confusion avec les "heures
        # prévues du mois" (calcul RÉEL, jour par jour, du module Paie).
        "heures_mois_moyenne": (Decimal(employee.weekly_hours) * Decimal("52") / Decimal("12")).quantize(Decimal("0.01")),
    }
    return render(request, "employees/employee_detail.html", context)

@login_required
@role_required("RH", "ADMIN")
def employee_create(request):
    form = EmployeeCreationForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        username = generate_username(form.cleaned_data["first_name"], form.cleaned_data["last_name"])
        temporary_password = generate_temporary_password()

        user = User.objects.create_user(
            username=username,
            email=form.cleaned_data["email"],
            first_name=form.cleaned_data["first_name"],
            last_name=form.cleaned_data["last_name"],
            role=form.cleaned_data["role"],
            password=temporary_password,
        )

        employee = form.save(commit=False)
        employee.user = user
        employee.save()

        email_sent = send_welcome_email(user, temporary_password)

        if email_sent:
            messages.success(
                request,
                f"Compte créé pour {employee} — identifiants envoyés par email à {user.email}."
            )
        else:
            # L'email n'est pas parti (pas de SMTP configuré, adresse invalide...) :
            # on affiche le mot de passe temporaire à l'écran pour ne pas bloquer la RH,
            # mais il faudra le transmettre à l'employé par un autre canal.
            messages.warning(
                request,
                f"Compte créé pour {employee}, mais l'email n'a pas pu être envoyé. "
                f"Identifiants à transmettre manuellement — nom d'utilisateur : {username} / "
                f"mot de passe temporaire : {temporary_password}"
            )
        return redirect("employees:detail", pk=employee.pk)

    return render(request, "employees/employee_form.html", {"form": form, "title": "Nouvel employé"})


@login_required
@role_required("RH", "ADMIN")
def employee_edit(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    form = EmployeeForm(request.POST or None, request.FILES or None, instance=employee)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Dossier employé mis à jour.")
        return redirect("employees:detail", pk=employee.pk)
    return render(request, "employees/employee_form.html", {"form": form, "title": f"Modifier {employee}"})


@login_required
@role_required("ADMIN")
def employee_delete(request, pk):
    """Suppression définitive d'un dossier employé (et du compte utilisateur
    associé) — réservée à l'Admin (cahier des charges v9 cap2)."""
    employee = get_object_or_404(Employee, pk=pk)
    if employee.user == request.user:
        messages.error(request, "Vous ne pouvez pas supprimer votre propre compte.")
        return redirect("employees:detail", pk=employee.pk)

    if request.method == "POST":
        name = str(employee)
        user = employee.user
        employee.delete()
        user.delete()
        messages.success(request, f"Le dossier de {name} a été supprimé.")
        return redirect("employees:list")

    return render(request, "employees/employee_confirm_delete.html", {"employee": employee})


@login_required
def document_upload(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.user.role == "EMPLOYEE" and employee.user != request.user:
        messages.error(request, "Accès refusé.")
        return redirect("accounts:dashboard")

    form = DocumentForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        doc = form.save(commit=False)
        doc.employee = employee
        doc.save()
        messages.success(request, "Document ajouté avec succès.")
        return redirect("employees:detail", pk=employee.pk)
    return render(request, "employees/document_form.html", {"form": form, "employee": employee})


def _can_manage_document(user, document):
    """RH/Admin peuvent tout gérer ; un employé ne gère que ses propres documents."""
    if user.role in ("RH", "ADMIN"):
        return True
    return document.employee.user == user


@login_required
def document_edit(request, doc_id):
    document = get_object_or_404(Document, pk=doc_id)
    if not _can_manage_document(request.user, document):
        messages.error(request, "Accès refusé.")
        return redirect("accounts:dashboard")

    form = DocumentForm(request.POST or None, request.FILES or None, instance=document)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Document mis à jour.")
        return redirect("employees:detail", pk=document.employee.pk)
    return render(request, "employees/document_form.html", {"form": form, "employee": document.employee, "editing": True})


@login_required
def document_delete(request, doc_id):
    document = get_object_or_404(Document, pk=doc_id)
    if not _can_manage_document(request.user, document):
        messages.error(request, "Accès refusé.")
        return redirect("accounts:dashboard")

    employee_pk = document.employee.pk
    document.file.delete(save=False)  # supprime aussi le fichier physique
    document.delete()
    messages.success(request, "Document supprimé.")
    return redirect("employees:detail", pk=employee_pk)


@login_required
def my_profile(request):
    """Auto-édition du profil : chaque utilisateur connecté (quel que soit
    son rôle) peut mettre à jour ses propres coordonnées et sa photo."""
    employee = getattr(request.user, "employee_profile", None)
    if not employee:
        messages.error(request, "Aucun dossier employé associé à ce compte.")
        return redirect("accounts:dashboard")

    form = MyProfileForm(request.POST or None, request.FILES or None, instance=employee, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Votre profil a été mis à jour.")
        return redirect("employees:my_profile")
    return render(request, "employees/my_profile.html", {"form": form, "employee": employee})


@login_required
@role_required("RH", "ADMIN")
def history_add(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    form = WorkHistoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        entry = form.save(commit=False)
        entry.employee = employee
        entry.save()
        messages.success(request, "Événement ajouté à l'historique.")
        return redirect("employees:detail", pk=employee.pk)
    return render(request, "employees/history_form.html", {"form": form, "employee": employee})


@login_required
def org_chart(request):
    managers = Employee.objects.filter(team_members__isnull=False).distinct()
    return render(request, "employees/org_chart.html", {"managers": managers})


# =====================================================================
# Contrats — historique complet par employé (RH/Admin gèrent, l'employé
# et son manager consultent en lecture seule).
# =====================================================================
@login_required
def contract_detail(request, contract_id):
    """Consultation en lecture seule d'un contrat. Accessible au salarié
    concerné (son propre contrat), à son manager, ainsi qu'à RH/Admin/
    Direction/Paie. Aucune action de modification n'est proposée ici — pour
    ça, la RH/Admin passe par contract_edit."""
    contract = get_object_or_404(Contract, pk=contract_id)
    employee = contract.employee

    if request.user.role == "EMPLOYEE":
        if employee.user_id != request.user.id:
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden("Vous ne pouvez consulter que votre propre contrat.")
    elif request.user.role == "MANAGER":
        manager_profile = getattr(request.user, "employee_profile", None)
        if employee.manager_id != getattr(manager_profile, "pk", None):
            from django.http import HttpResponseForbidden
            return HttpResponseForbidden("Vous ne pouvez consulter que les contrats de votre équipe.")
    # RH / ADMIN / DIRECTION / PAYROLL : consultation libre.

    return render(request, "employees/contract_detail.html", {"contract": contract, "employee": employee})

@login_required
@role_required("RH")
def contract_create(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    initial = {"job_title": employee.job_title, "department": employee.department_id}
    form = ContractForm(request.POST or None, request.FILES or None, initial=initial)

    if request.method == "POST" and form.is_valid():
        # Un seul contrat actif à la fois : on clôture automatiquement le précédent.
        previous_active = employee.contracts.filter(status=Contract.Status.ACTIVE).first()
        if previous_active:
            previous_active.status = Contract.Status.ENDED
            previous_active.end_reason = previous_active.end_reason or "Remplacé par un nouveau contrat"
            previous_active.save()

        contract = form.save(commit=False)
        contract.employee = employee
        contract.status = Contract.Status.ACTIVE
        contract.save()

        # Le nouveau contrat fait référence pour le poste/service affichés sur le dossier.
        employee.job_title = contract.job_title
        employee.department = contract.department
        employee.save()

        notify(
            recipient=employee.user,
            category=Notification.Category.CONTRACT_UPDATE,
            title="Nouveau contrat",
            message=(
                f"Un nouveau contrat ({contract.get_contract_type_display()}) a été créé pour vous, "
                f"poste : {contract.job_title}, à partir du {contract.start_date}."
            ),
            link=f"/employes/{employee.pk}/",
        )

        messages.success(request, f"Contrat {contract.contract_number} créé et activé pour {employee}.")
        return redirect("employees:detail", pk=employee.pk)

    return render(request, "employees/contract_form.html", {"form": form, "employee": employee, "title": "Nouveau contrat"})


@login_required
@role_required("RH")
def contract_edit(request, contract_id):
    contract = get_object_or_404(Contract, pk=contract_id)
    form = ContractForm(request.POST or None, request.FILES or None, instance=contract)
    if request.method == "POST" and form.is_valid():
        form.save()
        notify(
            recipient=contract.employee.user,
            category=Notification.Category.CONTRACT_UPDATE,
            title="Contrat modifié",
            message=f"Votre contrat {contract.contract_number} a été modifié par la RH.",
            link=f"/employes/{contract.employee.pk}/",
        )
        messages.success(request, "Contrat mis à jour.")
        return redirect("employees:detail", pk=contract.employee.pk)
    return render(request, "employees/contract_form.html", {"form": form, "employee": contract.employee, "title": f"Modifier {contract.contract_number}"})


@login_required
@role_required("RH")
def contract_end(request, contract_id):
    contract = get_object_or_404(Contract, pk=contract_id)
    form = ContractEndForm(request.POST or None, instance=contract)
    if request.method == "POST" and form.is_valid():
        contract.status = Contract.Status.ENDED
        form.save()
        notify(
            recipient=contract.employee.user,
            category=Notification.Category.CONTRACT_UPDATE,
            title="Contrat clôturé",
            message=f"Votre contrat {contract.contract_number} a été clôturé. Motif : {contract.end_reason or '—'}.",
            link=f"/employes/{contract.employee.pk}/",
        )
        messages.success(request, f"Contrat {contract.contract_number} clôturé.")
        return redirect("employees:detail", pk=contract.employee.pk)
    return render(request, "employees/contract_end_form.html", {"form": form, "contract": contract})

@login_required
@role_required("RH")
def contract_delete(request, contract_id):
    """Suppression DÉFINITIVE d'un contrat — réservée à la RH/Admin, avec
    confirmation explicite. À utiliser uniquement pour corriger une saisie
    erronée : pour un contrat réellement arrivé à échéance, préférez
    « Clôturer » (qui garde l'historique) plutôt que « Supprimer »."""
    contract = get_object_or_404(Contract, pk=contract_id)
    employee = contract.employee
    if request.method == "POST":
        numero = contract.contract_number
        contract.delete()
        notify(
            recipient=employee.user,
            category=Notification.Category.CONTRACT_UPDATE,
            title="Contrat supprimé",
            message=f"Votre contrat {numero} a été supprimé par la RH.",
            link=f"/employes/{employee.pk}/",
        )
        messages.success(request, f"Contrat {numero} supprimé définitivement.")
        return redirect("employees:detail", pk=employee.pk)
    return render(request, "employees/contract_confirm_delete.html", {"contract": contract, "employee": employee})