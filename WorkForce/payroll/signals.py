"""
Resynchronisation automatique de `Salary.base_amount`.

`Contract` + `SalaryHistory` sont désormais l'unique source de vérité du
salaire de base. `Salary.base_amount` n'est plus modifié à la main : il est
recalculé automatiquement (pour la date du jour) dès qu'un `Contract` ou un
`SalaryHistory` est enregistré, afin que les templates existants
(`salary_list`, `salary_detail`, `salary.total`...) continuent de fonctionner
sans changement.
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from employees.models import Contract
from .contract_utils import get_effective_base_salary
from .models import Salary, SalaryHistory

logger = logging.getLogger(__name__)


def _resync_salary(employee):
    today = timezone.localdate()
    amount = get_effective_base_salary(employee, today)
    if amount is None:
        return
    salary, _ = Salary.objects.get_or_create(employee=employee, defaults={"base_amount": amount})
    if salary.base_amount != amount:
        salary.base_amount = amount
        salary.save(update_fields=["base_amount", "updated_at"])


@receiver(post_save, sender=Contract)
def resync_salary_on_contract_save(sender, instance, **kwargs):
    try:
        _resync_salary(instance.employee)
    except Exception:
        logger.exception("Échec de la resynchronisation de Salary suite à l'enregistrement du contrat #%s", instance.pk)


@receiver(post_save, sender=SalaryHistory)
def resync_salary_on_history_save(sender, instance, **kwargs):
    try:
        _resync_salary(instance.employee)
    except Exception:
        logger.exception("Échec de la resynchronisation de Salary suite à l'historique de rémunération #%s", instance.pk)
