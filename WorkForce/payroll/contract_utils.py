"""
Résolution du contrat et du salaire applicables à une date donnée.

Principe validé avec l'utilisateur :
- `Contract` (employees/models.py) reste la source légale : type, dates,
  durée du CDD, temps de travail (heures/semaine, heures/jour, jours
  travaillés). Une augmentation de salaire NE modifie JAMAIS un `Contract`.
- `SalaryHistory` (payroll/models.py, déjà existant) porte les augmentations
  successives, chacune avec sa propre `effective_date`. `new_amount` est
  toujours le salaire total après l'augmentation (pas un delta).
- Pour reconstituer « le salaire en vigueur à la date X », on prend le
  `SalaryHistory` le plus récent dont `effective_date <= X` ; s'il n'y en a
  aucun, on retombe sur `Contract.base_salary` du contrat en vigueur à X.
- Ces fonctions sont volontairement en LECTURE SEULE : elles ne modifient ni
  Contract ni SalaryHistory. Elles servent à alimenter `payroll/utils.py`
  (calcul de la paie) et le signal de resynchronisation de `Salary`.
"""
from decimal import Decimal

from django.db.models import Q


def get_contract_on(employee, a_date):
    """Retourne le `Contract` en vigueur à `a_date` (ou None si aucun ne couvre cette date).

    Un contrat couvre `a_date` si `start_date <= a_date` et
    (`end_date` est vide OU `end_date >= a_date`).
    """
    return (
        employee.contracts
        .filter(start_date__lte=a_date)
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=a_date))
        .order_by("-start_date")
        .first()
    )


def get_effective_base_salary(employee, a_date):
    """Salaire de base applicable à `a_date` (Decimal), en combinant
    SalaryHistory (augmentations datées) et Contract (salaire à la signature).

    Retourne None si l'employé n'a ni contrat ni historique couvrant cette date
    (cas d'un employé legacy sans Contract enregistré et sans augmentation
    historisée : Salary.base_amount reste alors géré tel quel, sans écrasement).
    """
    from payroll.models import SalaryHistory

    contract = get_contract_on(employee, a_date)

    history_qs = SalaryHistory.objects.filter(employee=employee, effective_date__lte=a_date)
    if contract is not None:
        # Une augmentation n'a de sens que si elle s'applique après le début du
        # contrat en vigueur à cette date (on évite de faire "remonter" une
        # augmentation d'un contrat antérieur sur un tout nouveau contrat).
        history_qs = history_qs.filter(effective_date__gte=contract.start_date)

    latest_history = history_qs.order_by("-effective_date", "-id").first()
    if latest_history is not None:
        return latest_history.new_amount

    if contract is not None:
        return contract.base_salary

    return None


def get_effective_contract_terms(employee, a_date):
    """Regroupe toutes les données contractuelles applicables à `a_date`,
    utilisées par le calcul de paie (heures prévues, taux horaire, heures sup...).

    Retourne un dict, ou None si aucun contrat ne couvre `a_date` :
        {
            "contract": Contract,
            "base_salary": Decimal,   # salaire courant (contrat + augmentations)
            "bonuses": Decimal,       # primes contractuelles (Contract.bonuses)
            "weekly_hours": Decimal,
            "hours_per_day": Decimal,
            "work_days": [1, 2, 3, 4, 5],
            "work_time": "FULL_TIME" | "PART_TIME",
        }
    """
    contract = get_contract_on(employee, a_date)
    if contract is None:
        return None

    base_salary = get_effective_base_salary(employee, a_date)
    if base_salary is None:
        base_salary = contract.base_salary

    return {
        "contract": contract,
        "base_salary": Decimal(base_salary),
        "bonuses": Decimal(contract.bonuses),
        "weekly_hours": Decimal(contract.weekly_hours),
        "hours_per_day": Decimal(contract.hours_per_day),
        "work_days": contract.work_days_list,
        "work_time": contract.work_time,
    }
