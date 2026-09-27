from django.apps import AppConfig


class PayrollConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "payroll"
    verbose_name = "Paie & Salaires"

    def ready(self):
        from . import signals  # noqa: F401 — connecte la resynchronisation Salary <- Contract/SalaryHistory
