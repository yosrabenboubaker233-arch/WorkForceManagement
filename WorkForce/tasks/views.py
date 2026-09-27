from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages

from accounts.decorators import role_required
from .models import Task
from .forms import TaskForm, TaskStatusForm, TaskCommentForm
from notifications.models import Notification
from notifications.emailing import notify


@login_required
def my_tasks(request):
    employee = getattr(request.user, "employee_profile", None)
    tasks = Task.objects.filter(employee=employee).order_by("status", "due_date") if employee else []
    return render(request, "tasks/my_tasks.html", {"tasks": tasks, "employee": employee})


@login_required
@role_required("MANAGER")
def team_tasks(request):
    """Détail des tâches de l'équipe — réservé au Manager ."""
    manager_profile = getattr(request.user, "employee_profile", None)
    tasks = Task.objects.select_related("employee__user")
    if request.user.role == "MANAGER":
        tasks = tasks.filter(employee__manager=manager_profile)
    return render(request, "tasks/team_tasks.html", {"tasks": tasks.order_by("status", "due_date")})


@login_required
@role_required("MANAGER")
def task_create(request):
    manager_profile = getattr(request.user, "employee_profile", None)
    form = TaskForm(request.POST or None, manager=manager_profile)
    if request.method == "POST" and form.is_valid():
        task = form.save(commit=False)
        task.assigned_by = manager_profile
        task.save()

        notify(
            recipient=task.employee.user,
            category=Notification.Category.TASK_ASSIGNED,
            title="Nouvelle tâche assignée",
            message=f"{manager_profile} vous a assigné la tâche « {task.title} »"
                    + (f", à réaliser avant le {task.due_date}." if task.due_date else "."),
            link="/taches/",
        )
        messages.success(request, "Tâche assignée (notification application + email envoyée).")
        return redirect("tasks:team_tasks")

    return render(request, "tasks/task_form.html", {"form": form, "title": "Assigner une tâche"})


@login_required
@role_required("MANAGER")
def task_edit(request, pk):
    task = get_object_or_404(Task, pk=pk)
    manager_profile = getattr(request.user, "employee_profile", None)
    if request.user.role == "MANAGER" and task.assigned_by_id != getattr(manager_profile, "id", None):
        messages.error(request, "Vous ne pouvez modifier que les tâches que vous avez assignées.")
        return redirect("tasks:team_tasks")

    form = TaskForm(request.POST or None, instance=task, manager=task.employee.manager)
    if request.method == "POST" and form.is_valid():
        form.save()
        notify(
            recipient=task.employee.user,
            category=Notification.Category.TASK_ASSIGNED,
            title="Tâche modifiée",
            message=f"La tâche « {task.title} » a été modifiée par {request.user.get_full_name() or request.user.username}.",
            link="/taches/",
        )
        messages.success(request, "Tâche mise à jour.")
        return redirect("tasks:team_tasks")

    return render(request, "tasks/task_form.html", {"form": form, "title": f"Modifier « {task.title} »"})


@login_required
@role_required("MANAGER")
def task_delete(request, pk):
    task = get_object_or_404(Task, pk=pk)
    manager_profile = getattr(request.user, "employee_profile", None)
    if request.user.role == "MANAGER" and task.assigned_by_id != getattr(manager_profile, "id", None):
        messages.error(request, "Vous ne pouvez supprimer que les tâches que vous avez assignées.")
        return redirect("tasks:team_tasks")

    if request.method == "POST":
        titre = task.title
        employe = task.employee.user
        task.delete()
        notify(
            recipient=employe,
            category=Notification.Category.TASK_ASSIGNED,
            title="Tâche supprimée",
            message=f"La tâche « {titre} » a été supprimée par {request.user.get_full_name() or request.user.username}.",
            link="/taches/",
        )
        messages.success(request, f"Tâche « {titre} » supprimée.")
        return redirect("tasks:team_tasks")

    return render(request, "tasks/task_confirm_delete.html", {"task": task})


@login_required
def task_detail(request, pk):
    task = get_object_or_404(Task, pk=pk)
    employee = getattr(request.user, "employee_profile", None)

    is_owner = task.employee.user == request.user
    is_manager_of_owner = task.employee.manager and task.employee.manager.user == request.user
    if not (is_owner or is_manager_of_owner):
        messages.error(request, "Accès refusé à cette tâche.")
        return redirect("accounts:dashboard")

    status_form = TaskStatusForm(instance=task)
    comment_form = TaskCommentForm()

    if request.method == "POST":
        if "update_status" in request.POST and is_owner:
            status_form = TaskStatusForm(request.POST, instance=task)
            if status_form.is_valid():
                status_form.save()
                if task.assigned_by:
                    notify(
                        recipient=task.assigned_by.user,
                        category=Notification.Category.TASK_STATUS,
                        title="Statut de tâche mis à jour",
                        message=f"{task.employee} a mis à jour le statut de « {task.title} » : {task.get_status_display()}.",
                        link="/taches/equipe/",
                    )
                messages.success(request, "Statut mis à jour.")
                return redirect("tasks:detail", pk=task.pk)

        elif "add_comment" in request.POST:
            comment_form = TaskCommentForm(request.POST, request.FILES)
            if comment_form.is_valid():
                comment = comment_form.save(commit=False)
                comment.task = task
                comment.author = request.user
                comment.save()

                destinataire = None
                if is_owner and task.assigned_by:
                    destinataire = task.assigned_by.user
                elif not is_owner:
                    destinataire = task.employee.user

                if destinataire:
                    apercu = comment.message[:120] if comment.message else f"📎 rapport joint : {comment.report_name}"
                    notify(
                        recipient=destinataire,
                        category=Notification.Category.TASK_COMMENT,
                        title="Nouveau commentaire sur une tâche",
                        message=f"{request.user.get_full_name() or request.user.username} a commenté « {task.title} » : {apercu}",
                        link=f"/taches/{task.pk}/",
                    )
                return redirect("tasks:detail", pk=task.pk)

    return render(request, "tasks/task_detail.html", {
        "task": task, "status_form": status_form, "comment_form": comment_form,
        "is_owner": is_owner, "comments": task.comments.select_related("author"),
    })