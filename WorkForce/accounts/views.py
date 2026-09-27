from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils import timezone

from .forms import WorkforceLoginForm
from accounts.models import User
from employees.models import Employee
from leaves.models import LeaveRequest, Authorization
from attendance.models import Attendance, AbsenceAlert
from notifications.models import Notification
from tasks.models import Task


class WorkforceLoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = WorkforceLoginForm
    redirect_authenticated_user = True


@login_required
def dashboard(request):
    user = request.user

    if user.role == user.Role.EMPLOYEE:
        from payroll.models import SalaryIncreaseProposal

        employee = getattr(user, "employee_profile", None)
        my_leaves = LeaveRequest.objects.filter(employee=employee).order_by("-created_at")[:5] if employee else []
        my_attendance = Attendance.objects.filter(employee=employee).order_by("-date")[:7] if employee else []
        my_salary = getattr(employee, "salary", None) if employee else None
        last_increase = employee.salary_history.first() if employee else None
        my_pending_proposal = (
            employee.salary_proposals.exclude(
                status__in=[SalaryIncreaseProposal.Status.REJECTED, SalaryIncreaseProposal.Status.APPLIED]
            ).first()
            if employee else None
        )
        context = {
            "employee": employee,
            "my_leaves": my_leaves,
            "my_attendance": my_attendance,
            "my_salary": my_salary,
            "last_increase": last_increase,
            "my_pending_proposal": my_pending_proposal,
        }
        return render(request, "dashboard/employee_dashboard.html", context)

    if user.role == user.Role.MANAGER:
        from payroll.models import SalaryIncreaseProposal

        manager_employee = getattr(user, "employee_profile", None)
        team = Employee.objects.filter(manager=manager_employee) if manager_employee else Employee.objects.none()
        pending_leaves = LeaveRequest.objects.filter(
            employee__in=team, status=LeaveRequest.Status.PENDING_STEP1
        )
        alerts = AbsenceAlert.objects.filter(employee__in=team, resolved=False).order_by("-created_at")
        my_proposals = SalaryIncreaseProposal.objects.filter(proposed_by=user).select_related("employee__user")
        my_proposals_pending = my_proposals.exclude(
            status__in=[SalaryIncreaseProposal.Status.REJECTED, SalaryIncreaseProposal.Status.APPLIED]
        ).count()
        context = {
            "team": team,
            "pending_leaves": pending_leaves,
            "alerts": alerts,
            "my_proposals_pending": my_proposals_pending,
            "my_proposals_recent": my_proposals.order_by("-proposed_at")[:5],
        }
        return render(request, "dashboard/manager_dashboard.html", context)

    if user.role in (user.Role.RH, user.Role.ADMIN):
        from payroll.models import SalaryIncreaseProposal
        context = {
            "total_employees": Employee.objects.count(),
            "pending_leaves": LeaveRequest.objects.filter(
                status__in=[LeaveRequest.Status.PENDING_STEP1, LeaveRequest.Status.PENDING_STEP2]
            ).count(),
            "pending_step2": LeaveRequest.objects.filter(status=LeaveRequest.Status.PENDING_STEP2).count()
            + Authorization.objects.filter(status=Authorization.Status.PENDING_STEP2).count(),
            "today_absences": Attendance.objects.filter(status=Attendance.Status.ABSENT).count(),
            "open_alerts": AbsenceAlert.objects.filter(resolved=False).count(),
            "payroll_to_process": LeaveRequest.objects.filter(payroll_status="TO_PROCESS").count()
            + Authorization.objects.filter(payroll_status="TO_PROCESS").count(),
            "proposals_pending_rh": SalaryIncreaseProposal.objects.filter(
                status=SalaryIncreaseProposal.Status.PENDING_RH
            ).count(),
        }
        return render(request, "dashboard/rh_dashboard.html", context)

    if user.role == user.Role.PAYROLL:
        from payroll.models import Salary, SalaryIncreaseProposal
        context = {
            "salaries": Salary.objects.select_related("employee").all()[:10],
            "payroll_to_process": LeaveRequest.objects.filter(payroll_status="TO_PROCESS").count()
            + Authorization.objects.filter(payroll_status="TO_PROCESS").count(),
            "proposals_to_apply": SalaryIncreaseProposal.objects.filter(
                status=SalaryIncreaseProposal.Status.APPROVED
            ).count(),
        }
        return render(request, "dashboard/payroll_dashboard.html", context)

    if user.role == user.Role.DIRECTION:
        from payroll.models import SalaryIncreaseProposal
        from leaves.views import _auto_expire

        today = timezone.localdate()

        pending_leaves = _auto_expire(LeaveRequest.objects.filter(
            status=LeaveRequest.Status.PENDING_STEP1, step1_role="DIRECTION"
        ).select_related("employee__user"))
        pending_auths = _auto_expire(Authorization.objects.filter(
            status=Authorization.Status.PENDING_STEP1, step1_role="DIRECTION"
        ).select_related("employee__user"))

        total_employees = Employee.objects.filter(status=Employee.Status.ACTIVE).count()
        present_today = Attendance.objects.filter(date=today, status=Attendance.Status.PRESENT).count()
        absent_today = Attendance.objects.filter(date=today, status=Attendance.Status.ABSENT).count()

        # --- Vue agrégée par manager : effectif + avancement des tâches ---
        # (le CEO voit les chiffres, pas le détail de chaque tâche — cahier des charges v6)
        teams = []
        managers = Employee.objects.filter(team_members__isnull=False).distinct()
        for manager in managers:
            team_members = Employee.objects.filter(manager=manager)
            team_tasks = Task.objects.filter(employee__in=team_members)
            total_tasks = team_tasks.count()
            done = team_tasks.filter(status=Task.Status.DONE).count()
            in_progress = team_tasks.filter(status=Task.Status.IN_PROGRESS).count()
            late = sum(1 for t in team_tasks if t.is_overdue)
            completion = round((done / total_tasks) * 100) if total_tasks else 0
            teams.append({
                "manager": manager,
                "employee_count": team_members.count(),
                "total_tasks": total_tasks,
                "done": done,
                "in_progress": in_progress,
                "late": late,
                "completion": completion,
            })

        proposals_pending_direction = SalaryIncreaseProposal.objects.filter(
            status=SalaryIncreaseProposal.Status.PENDING_DIRECTION
        ).select_related("employee__user", "rh_reviewed_by")

        context = {
            "pending_leaves": pending_leaves,
            "pending_auths": pending_auths,
            "total_employees": total_employees,
            "present_today": present_today,
            "absent_today": absent_today,
            "teams": teams,
            "open_alerts": AbsenceAlert.objects.filter(resolved=False).count(),
            "late_tasks_total": sum(t["late"] for t in teams),
            "proposals_pending_direction": proposals_pending_direction,
        }
        return render(request, "dashboard/direction_dashboard.html", context)

    return redirect("accounts:login")