"""
Cumul automatique du solde de congés — référence annuelle : 26 jours/an
(settings.ANNUAL_LEAVE_DAYS), soit environ 2,17 jour/mois calculé et cumulé
automatiquement.

À planifier une fois par mois (le 1er du mois, par exemple), indépendamment
de toute connexion à l'application :

    0 6 1 * * cd /chemin/du/projet && python manage.py accrue_leave_balance

Idempotent au sein du même mois calendaire : la commande n'ajoute
qu'une seule fois le crédit mensuel par employé (voir Employee.last_accrual_month).
"""
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from employees.models import Employee

# Dérivé d'une référence annuelle unique et configurable (§2) plutôt que
# d'une constante mensuelle codée en dur et déconnectée du total annuel.
ANNUAL_LEAVE_DAYS = Decimal(str(getattr(settings, "ANNUAL_LEAVE_DAYS", 26)))
ACCRUAL = (ANNUAL_LEAVE_DAYS / Decimal("12")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Command(BaseCommand):
    help = "Crédite automatiquement le solde de congés mensuel de chaque employé actif."

    def handle(self, *args, **options):
        today = timezone.localdate()
        current_month_key = today.strftime("%Y-%m")
        credited = 0

        for employee in Employee.objects.filter(status=Employee.Status.ACTIVE):
            if employee.last_accrual_month == current_month_key:
                continue  # déjà crédité ce mois-ci

            employee.leave_balance_days += ACCRUAL
            employee.last_accrual_month = current_month_key
            employee.save(update_fields=["leave_balance_days", "last_accrual_month"])
            credited += 1

        self.stdout.write(self.style.SUCCESS(
            f"{credited} employé(s) crédité(s) de {ACCRUAL} jour(s) pour {current_month_key}."
        ))
