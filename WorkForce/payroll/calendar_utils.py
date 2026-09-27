"""
Calcul des jours ouvrables et des heures prévues du mois.

Règle demandée :
    Heures prévues du mois = nombre de jours ouvrables × heures par jour

Le calendrier tient compte :
- des jours travaillés définis dans le `Contract` (`work_days_list`, ex :
  lundi-vendredi) ;
- des jours fériés (`PublicHoliday`), qui ne sont jamais des jours ouvrables ;
- du fait que le contrat en vigueur peut changer EN COURS DE MOIS (ex :
  changement de contrat le 15) : chaque jour du mois est évalué avec le
  contrat réellement actif ce jour-là (voir `contract_utils.get_contract_on`),
  jamais avec un contrat unique supposé valable tout le mois.

Ces fonctions sont en lecture seule et n'écrivent jamais en base.
"""
import calendar
from datetime import date
from decimal import Decimal

from .contract_utils import get_contract_on
from .models import PublicHoliday


def _all_dates_in_month(year, month):
    nb_jours = calendar.monthrange(year, month)[1]
    return [date(year, month, day) for day in range(1, nb_jours + 1)]


def jours_ouvrables_du_mois(employee, year, month):
    """Liste des (date, contract) pour chaque jour ouvrable du mois, en
    tenant compte du contrat réellement en vigueur ce jour-là et des jours
    fériés. Un jour sans contrat actif n'est jamais compté comme ouvrable."""
    holiday_dates = set(
        PublicHoliday.objects.filter(date__year=year, date__month=month).values_list("date", flat=True)
    )

    resultat = []
    for jour in _all_dates_in_month(year, month):
        if jour in holiday_dates:
            continue
        contract = get_contract_on(employee, jour)
        if contract is None:
            continue
        if jour.isoweekday() in contract.work_days_list:
            resultat.append((jour, contract))
    return resultat


def heures_prevues_mois(employee, year, month):
    """Heures prévues du mois (Decimal) = somme, pour chaque jour ouvrable,
    des heures/jour du contrat en vigueur ce jour-là.

    Exemple (contrat constant sur le mois, 8h/jour, lundi-vendredi) :
        21 jours ouvrables -> 168 h
        22 jours ouvrables -> 176 h

    NB : si le contrat de l'employé a démarré (ou s'est terminé) EN COURS
    de ce mois, seuls les jours réellement couverts par un contrat sont
    comptés — le total est donc logiquement plus faible qu'un mois complet
    (voir `mois_est_partiel` / `jours_couverts_mois` ci-dessous, utilisés
    par l'affichage pour l'expliquer clairement plutôt que de laisser
    penser à une erreur de calcul)."""
    total = Decimal("0")
    for _jour, contract in jours_ouvrables_du_mois(employee, year, month):
        total += Decimal(contract.hours_per_day)
    return total


def jours_couverts_mois(employee, year, month):
    """Nombre de jours calendaires du mois couverts par UN contrat (actif ce
    jour-là), sur le nombre total de jours du mois. Permet d'expliquer à
    l'affichage un total d'heures prévues plus faible que d'habitude
    (contrat qui démarre ou se termine en cours de mois)."""
    from .contract_utils import get_contract_on
    nb_total = calendar.monthrange(year, month)[1]
    nb_couverts = sum(
        1 for jour in _all_dates_in_month(year, month) if get_contract_on(employee, jour) is not None
    )
    return nb_couverts, nb_total


def nb_jours_ouvrables_mois(employee, year, month):
    """Nombre de jours ouvrables du mois (entier), pratique pour l'affichage."""
    return len(jours_ouvrables_du_mois(employee, year, month))


def is_jour_ferie(a_date):
    return PublicHoliday.objects.filter(date=a_date).exists()


def is_jour_repos(employee, a_date):
    """Un jour est un jour de repos si le contrat en vigueur ce jour-là ne
    le liste pas parmi ses jours travaillés (ex : samedi/dimanche pour un
    contrat lundi-vendredi). Un jour sans contrat actif est considéré repos
    par défaut (rien n'est dû à l'employé ce jour-là)."""
    contract = get_contract_on(employee, a_date)
    if contract is None:
        return True
    return a_date.isoweekday() not in contract.work_days_list