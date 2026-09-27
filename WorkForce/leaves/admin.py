from django.contrib import admin
from .models import LeaveType, LeaveRequest, Authorization, LeaveBalanceTransaction


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "paid", "treatment", "reduces_annual_balance")


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ("employee", "leave_type", "start_date", "end_date", "status", "payroll_status", "created_at")
    list_filter = ("status", "payroll_status", "leave_type")
    search_fields = ("employee__user__first_name", "employee__user__last_name")


@admin.register(Authorization)
class AuthorizationAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "start_time", "end_time", "duration_hours", "treatment", "status", "payroll_status")
    list_filter = ("status", "payroll_status", "treatment")
    search_fields = ("employee__user__first_name", "employee__user__last_name")


@admin.register(LeaveBalanceTransaction)
class LeaveBalanceTransactionAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "source", "hours_consumed", "days_converted", "balance_before", "balance_after")
    list_filter = ("source", "date")
    search_fields = ("employee__user__first_name", "employee__user__last_name")
    readonly_fields = [f.name for f in LeaveBalanceTransaction._meta.fields]

    def has_add_permission(self, request):
        return False  # traçabilité générée par le système uniquement, jamais créée à la main

    def has_change_permission(self, request, obj=None):
        return False
