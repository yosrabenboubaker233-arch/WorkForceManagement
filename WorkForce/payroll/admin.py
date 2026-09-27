from django.contrib import admin
from .models import Salary, SalaryHistory, PublicHoliday, PayrollPolicy, PayslipRecord


@admin.register(PayslipRecord)
class PayslipRecordAdmin(admin.ModelAdmin):
    list_display = ("employee", "month", "year", "gross_amount", "net_amount", "status")
    list_filter = ("status", "year", "month")
    search_fields = ("employee__first_name", "employee__last_name")


@admin.register(Salary)
class SalaryAdmin(admin.ModelAdmin):
    list_display = ("employee", "base_amount", "bonus", "benefits", "total", "currency")


@admin.register(SalaryHistory)
class SalaryHistoryAdmin(admin.ModelAdmin):
    list_display = ("employee", "previous_amount", "new_amount", "percentage", "effective_date")
    list_filter = ("effective_date",)


@admin.register(PublicHoliday)
class PublicHolidayAdmin(admin.ModelAdmin):
    list_display = ("label", "date")
    list_filter = ("date",)


@admin.register(PayrollPolicy)
class PayrollPolicyAdmin(admin.ModelAdmin):
    list_display = ("hourly_rate_method", "overtime_rate_1", "overtime_rate_2", "internal_weekly_overtime_limit_percent")

    def has_add_permission(self, request):
        # Singleton : on ne peut créer qu'une seule ligne (get_solo() la crée si besoin).
        return not PayrollPolicy.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False