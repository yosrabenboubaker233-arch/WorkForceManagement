"""
Calculs utilitaires pour la paie (cahier des charges v3 §9, v9 §1, v14) :
heures supplémentaires, coût d'augmentation, calcul du bulletin de paie
et génération du PDF téléchargeable.

Les taux de cotisation (CNSS, CSS, barème IRPP) sont désormais une donnée
MÉTIER gérée par la Paie depuis l'interface (modèle PayrollRateSet /
PayrollRateBracket, historisée par date d'effet) — voir payroll/models.py
et la vue payroll_rates_list / payroll_rate_create. Les constantes de
settings.py ne servent plus que de secours si aucun barème n'a encore été
saisi (première utilisation, avant toute configuration par la Paie).
"""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db.models import Q
from attendance.models import Attendance
from .calendar_utils import is_jour_ferie, is_jour_repos
from .contract_utils import get_contract_on

# Valeurs de secours (utilisées uniquement si aucun PayrollRateSet n'existe
# encore en base — cf. _get_active_rate_set ci-dessous).
_FALLBACK_CNSS_RATE = Decimal(str(getattr(settings, "TAUX_CNSS_SALARIE", 0.0918))) * 100
_FALLBACK_CSS_RATE = Decimal(str(getattr(settings, "TAUX_CSS_SALARIE", 0.005))) * 100
_FALLBACK_BAREME_IRPP = getattr(settings, "BAREME_IRPP", [(5000, 0.0), (None, 0.30)])


def _monday_of_week(a_date):
    return a_date - timedelta(days=a_date.isoweekday() - 1)


def _weeks_covering_month(year, month):
    """Liste des semaines ISO (lundi -> dimanche) qui touchent au moins un
    jour du mois `year`/`month` (peut donc déborder sur le mois précédent
    ou suivant)."""
    import calendar as _calendar
    first_day = date(year, month, 1)
    last_day = date(year, month, _calendar.monthrange(year, month)[1])

    semaines = []
    lundi = _monday_of_week(first_day)
    while lundi <= last_day:
        semaines.append((lundi, lundi + timedelta(days=6)))
        lundi += timedelta(days=7)
    return semaines


def compute_overtime_hours(employee, year, month):
    """Calcule les heures normales / supplémentaires / jour de repos / jour
    férié / à récupérer, pour le MOIS DE PAIE demandé uniquement — mais en
    analysant chaque semaine ISO dans son intégralité pour déterminer le
    dépassement hebdomadaire (§3, §4 des précisions client).

    Méthode de répartition entre deux mois pour une semaine à cheval
    (documentée explicitement, cf. demande client) :
    au sein de chaque semaine, les jours sont traités dans l'ordre
    chronologique et un total cumulé (`running_total`) est maintenu jour
    après jour. Les heures de chaque jour sont classées (normales / taux 1 /
    taux 2) selon la position du cumul AVANT et APRÈS ce jour par rapport aux
    seuils hebdomadaires — puis ce jour classé est attribué à SON PROPRE mois
    calendaire. Ainsi, si une semaine de 48h a 40h en juillet et 8h en août,
    les 8h d'août sont bien les heures qui, chronologiquement, dépassent le
    seuil de 40h : elles sont donc classées "heures supplémentaires" et
    attribuées à août. Juillet ne reçoit que des heures normales. Ce choix
    (attribution chronologique jour par jour) est plus précis qu'un simple
    prorata global et évite de faire porter des heures supplémentaires sur
    un mois où elles n'ont pas été physiquement travaillées.

    Retourne un dict Decimal :
        normal_hours, overtime_tier1_hours, overtime_tier2_hours,
        rest_day_hours, holiday_hours, recoverable_hours,
        total_worked_hours, weekly_alerts (liste des semaines où la limite
        interne d'heures sup. est dépassée, pour la partie retenue sur ce mois).
    """
    from .models import PayrollPolicy

    policy = PayrollPolicy.get_solo()

    resultat = {
        "normal_hours": Decimal("0"),
        "overtime_tier1_hours": Decimal("0"),
        "overtime_tier2_hours": Decimal("0"),
        "rest_day_hours": Decimal("0"),
        "holiday_hours": Decimal("0"),
        "recoverable_hours": Decimal("0"),
        "total_worked_hours": Decimal("0"),
        "weekly_alerts": [],
    }

    semaines = _weeks_covering_month(year, month)
    if not semaines:
        return resultat

    debut = semaines[0][0]
    fin = semaines[-1][1]
    attendances_par_jour = {
        a.date: a for a in Attendance.objects.filter(employee=employee, date__range=(debut, fin))
    }

    for lundi, dimanche in semaines:
        running_total = Decimal("0")
        semaine_normal = Decimal("0")
        semaine_tier1 = Decimal("0")
        semaine_tier2 = Decimal("0")

        jour = lundi
        while jour <= dimanche:
            attendance = attendances_par_jour.get(jour)
            worked = attendance.worked_hours_decimal if attendance else Decimal("0")

            if worked > 0:
                contract = get_contract_on(employee, jour)
                weekly_hours = Decimal(contract.weekly_hours) if contract else Decimal("40")
                tier2_threshold = Decimal(policy.overtime_tier2_threshold_hours)

                if is_jour_ferie(jour):
                    if jour.month == month and jour.year == year:
                        resultat["holiday_hours"] += worked
                        resultat["total_worked_hours"] += worked
                elif is_jour_repos(employee, jour) and policy.rest_day_policy == PayrollPolicy.RestDayPolicy.SPECIAL_RATE:
                    if jour.month == month and jour.year == year:
                        resultat["rest_day_hours"] += worked
                        resultat["total_worked_hours"] += worked
                elif is_jour_repos(employee, jour) and policy.rest_day_policy == PayrollPolicy.RestDayPolicy.TIME_OFF_IN_LIEU:
                    if jour.month == month and jour.year == year:
                        resultat["recoverable_hours"] += worked
                        resultat["total_worked_hours"] += worked
                else:
                    # Jour du "pool hebdomadaire" : jour contractuel normal, ou
                    # jour de repos traité selon la politique WEEKLY_THRESHOLD
                    # (il compte dans le total hebdo comme n'importe quel jour).
                    avant = running_total
                    apres = running_total + worked

                    part_normale = max(Decimal("0"), min(apres, weekly_hours) - avant)
                    part_tier1 = max(Decimal("0"), min(apres, tier2_threshold) - max(avant, weekly_hours))
                    part_tier2 = max(Decimal("0"), apres - max(avant, tier2_threshold))

                    running_total = apres
                    semaine_normal += part_normale
                    semaine_tier1 += part_tier1
                    semaine_tier2 += part_tier2

                    if jour.month == month and jour.year == year:
                        resultat["normal_hours"] += part_normale
                        resultat["overtime_tier1_hours"] += part_tier1
                        resultat["overtime_tier2_hours"] += part_tier2
                        resultat["total_worked_hours"] += worked

            jour += timedelta(days=1)

        # Limite interne d'heures sup./semaine  — purement informative,
        # ne bloque rien, sert à générer une alerte + demande de validation RH.
        contract_semaine = get_contract_on(employee, lundi) or get_contract_on(employee, dimanche)
        weekly_hours_ref = Decimal(contract_semaine.weekly_hours) if contract_semaine else Decimal("40")
        limite_heures = (weekly_hours_ref * policy.internal_weekly_overtime_limit_percent / Decimal("100"))
        heures_sup_semaine = semaine_tier1 + semaine_tier2
        if heures_sup_semaine > limite_heures:
            resultat["weekly_alerts"].append({
                "week_start": lundi, "week_end": dimanche,
                "overtime_hours": heures_sup_semaine, "limit_hours": limite_heures,
                "excess_hours": heures_sup_semaine - limite_heures,
            })

    return resultat

def compute_absence_deduction(employee, year, month, hourly_rate):
    """Retenue pour absences sur le mois, motif par motif ( des précisions
    client) — plus aucune déduction automatique et uniforme de tout jour
    `ABSENT`. Pour chaque jour ouvrable du mois (d'après le contrat en
    vigueur ce jour-là, cf. calendar_utils), on détermine le motif réel :

      - Pointage effectué (présent/en retard)         -> aucune déduction
      - Congé approuvé couvrant le jour                -> LeaveType.treatment
      - Autorisation approuvée couvrant toute la durée  -> Authorization.treatment
      - Absence sans congé ni autorisation              -> AbsenceAlert.treatment
        (créée par `detect_absences` ; DEDUCTIBLE par défaut tant que la RH
        n'a pas statué sur une justification)
      - Fiche de pointage existante mais sans alerte associée (cas résiduel)
        -> traité prudemment comme DEDUCTIBLE
      - Aucune trace du tout (ni pointage, ni congé, ni autorisation, ni
        alerte — `detect_absences` n'a jamais tourné ce jour-là, typiquement
        un mois antérieur à la mise en service du pointage) -> ignoré : ce
        n'est pas une absence, juste une période jamais contrôlée par le
        système, donc ni comptée ni affichée dans le détail.

    Seuls les jours au traitement DEDUCTIBLE réduisent le salaire. Les jours
    RECOVERABLE sont comptés à part (à récupérer, ni payés ni déduits) et
    n'impactent pas le montant retenu.

    Retourne un dict :
        deduction_amount   : Decimal (montant retenu sur le salaire)
        deductible_hours   : Decimal
        recoverable_hours  : Decimal
        no_deduction_hours : Decimal (congé payé, autorisation non déductible, etc.)
        details            : liste de {date, hours, treatment, reason}
    """
    from leaves.models import LeaveRequest, Authorization, PayrollTreatment
    from attendance.models import AbsenceAlert
    from .calendar_utils import jours_ouvrables_du_mois
    from django.utils import timezone

    deductible_hours = Decimal("0")
    recoverable_hours = Decimal("0")
    no_deduction_hours = Decimal("0")
    details = []
    today = timezone.localdate()

    for jour, contract in jours_ouvrables_du_mois(employee, year, month):
        if jour > today:
            continue

        hours_per_day = Decimal(contract.hours_per_day)

        attendance = Attendance.objects.filter(employee=employee, date=jour).first()

        # Pointage effectué -> l'employé a travaillé ce jour, rien à déduire
        # ici (les écarts horaires sont traités séparément par le calcul des
        # heures supplémentaires, jamais par une déduction d'absence).
        if attendance and attendance.check_in:
            continue

        treatment = None
        reason = ""

        leave = LeaveRequest.objects.filter(
            employee=employee, status=LeaveRequest.Status.APPROVED,
            start_date__lte=jour, end_date__gte=jour,
        ).select_related("leave_type").first()
        if leave:
            treatment = leave.leave_type.treatment
            reason = f"Congé : {leave.leave_type.name}"
        else:
            authorization = Authorization.objects.filter(
                employee=employee, date=jour, status=Authorization.Status.APPROVED,
            ).first()
            if authorization and authorization.duration_hours >= hours_per_day:
                treatment = authorization.treatment
                reason = f"Autorisation : {authorization.get_kind_display()}"
            else:
                alert = AbsenceAlert.objects.filter(employee=employee, date=jour).first()
                if alert:
                    treatment = alert.treatment
                    reason = "Absence justifiée" if alert.justified else "Absence non justifiée"
                elif attendance is not None:
                    # Une fiche de pointage existe pour ce jour (créée par
                    # check_workday_alerts/detect_absences, donc le contrôle
                    # quotidien a bien tourné), mais sans alerte associée :
                    # cas résiduel, traité prudemment comme déductible —
                    # comportement historique inchangé.
                    treatment = PayrollTreatment.DEDUCTIBLE
                    reason = "Absence non couverte (aucun pointage ni justificatif enregistré)"
                else:
                    continue

        if treatment == PayrollTreatment.DEDUCTIBLE:
            deductible_hours += hours_per_day
        elif treatment == PayrollTreatment.RECOVERABLE:
            recoverable_hours += hours_per_day
        else:  # NO_DEDUCTION
            no_deduction_hours += hours_per_day

        details.append({"date": jour, "hours": hours_per_day, "treatment": treatment, "reason": reason})

    deduction_amount = (deductible_hours * hourly_rate).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    return {
        "deduction_amount": deduction_amount,
        "deductible_hours": deductible_hours,
        "recoverable_hours": recoverable_hours,
        "no_deduction_hours": no_deduction_hours,
        "details": details,
    }


def compute_raise_annual_cost(previous_amount, new_amount):
    """Coût annuel d'une augmentation = (nouveau − ancien) × 12."""
    return (Decimal(new_amount) - Decimal(previous_amount)) * 12


def _get_active_rate_set(reference_date):
    """Renvoie le PayrollRateSet applicable à la date donnée (le barème le
    plus récent dont la date d'effet ne dépasse pas `reference_date`), géré
    par la Paie depuis l'interface. Si aucun barème n'a encore été
    configuré, renvoie None (les valeurs de secours sont alors utilisées)."""
    from .models import PayrollRateSet  # import tardif pour éviter les imports circulaires
    return PayrollRateSet.active_for(reference_date)


def _irpp_annuel(base_annuelle, bareme):
    """IRPP simplifié par tranches progressives. `bareme` est une liste de
    tuples (plafond_ou_None, taux_en_fraction). Ne remplace pas un vrai
    calcul réglementaire — barème saisi et tenu à jour par la Paie."""
    base_annuelle = Decimal(base_annuelle)
    if base_annuelle <= 0:
        return Decimal("0")

    impot = Decimal("0")
    borne_precedente = Decimal("0")
    for borne, taux in bareme:
        taux = Decimal(str(taux))
        borne_actuelle = Decimal(str(borne)) if borne is not None else None
        if borne_actuelle is None or base_annuelle <= borne_actuelle:
            tranche = base_annuelle - borne_precedente
            impot += tranche * taux
            break
        else:
            tranche = borne_actuelle - borne_precedente
            impot += tranche * taux
            borne_precedente = borne_actuelle

    return impot.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def build_payslip(salary, month, year, hourly_rate_override=None, notify_overtime_alerts=False):
    """Construit toutes les lignes d'un bulletin de paie pour un salarié,
    pour un mois/année donnés (cahier des charges, modèle tunisien
    simplifié : salaire de base + primes + indemnités + heures sup,
    puis CNSS, IRPP, CSS et retenues absences).

    Étape 7 — intégration complète :
    - Le salaire de base et les primes contractuelles viennent du CONTRAT en
      vigueur en début de mois (`contract_utils.get_effective_contract_terms`),
      pas de `Salary.base_amount` lu isolément (qui n'est qu'un reflet
      synchronisé automatiquement, cf. payroll/signals.py).
    - Le taux horaire suit la méthode choisie dans `PayrollPolicy`.
    - Les heures supplémentaires (normales/taux 1/taux 2/jour de repos/jour
      férié) viennent de `compute_overtime_hours`, avec les coefficients de
      `PayrollPolicy`.
    - La retenue d'absences vient de `compute_absence_deduction`, motif par
      motif — plus de déduction uniforme.
    - Si `notify_overtime_alerts=True` (génération réelle, pas un aperçu) et
      qu'une semaine dépasse la limite interne d'heures sup., la RH est
      notifiée (§8).

    Les taux de cotisation appliqués sont ceux du barème saisi par la Paie et
    en vigueur à la date de la période de paie — voir PayrollRateSet.active_for().
    """
    from .contract_utils import get_effective_contract_terms
    from .calendar_utils import heures_prevues_mois
    from .models import PayrollPolicy
    import calendar as _calendar

    employee = salary.employee
    dernier_jour_mois = _calendar.monthrange(year, month)[1]
    debut_mois = date(year, month, 1)
    fin_mois = date(year, month, dernier_jour_mois)
    reference_date = fin_mois

    # Le mois est-il couvert, ne serait-ce qu'un seul jour, par un contrat ?
    a_un_contrat_ce_mois = employee.contracts.filter(
        start_date__lte=fin_mois
    ).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=debut_mois)
    ).exists()
    a_deja_eu_un_contrat = employee.contracts.exists()

    terms = get_effective_contract_terms(employee, reference_date)
    hors_contrat = False
    if terms is not None:
        base = terms["base_salary"]
        primes_contractuelles = terms["bonuses"]
    elif not a_deja_eu_un_contrat:
        # Employé , jamais migré vers Contract : comportement
        # historique préservé (on retombe sur Salary tel quel).
        base = salary.base_amount
        primes_contractuelles = Decimal("0")
    else:
        # L'employé A des contrats, mais AUCUN ne couvre ce mois (mois
        # antérieur à l'embauche, ou trou entre deux contrats) : on ne
        # fabrique JAMAIS un bulletin à partir du salaire actuel pour un
        # mois où l'employé n'était sous aucun contrat — cela reviendrait à
        # le payer pour un mois non travaillé/non contractuel.
        base = Decimal("0")
        primes_contractuelles = Decimal("0")
        hors_contrat = True

    prime_presence = Decimal("0") if hors_contrat else salary.presence_bonus
    indemnite_transport = Decimal("0") if hors_contrat else salary.transport_allowance
    autres_primes = Decimal("0") if hors_contrat else (salary.bonus + salary.benefits + primes_contractuelles)

    rate_set = _get_active_rate_set(reference_date)
    if rate_set is not None:
        taux_cnss = rate_set.cnss_rate / Decimal("100")
        taux_css = rate_set.css_rate / Decimal("100")
        bareme_irpp = [(b.upper_bound, b.rate / Decimal("100")) for b in rate_set.brackets.all()]
        if not bareme_irpp:
            bareme_irpp = [(Decimal(str(b)) if b is not None else None, t) for b, t in _FALLBACK_BAREME_IRPP]
    else:
        taux_cnss = _FALLBACK_CNSS_RATE / Decimal("100")
        taux_css = _FALLBACK_CSS_RATE / Decimal("100")
        bareme_irpp = [(Decimal(str(b)) if b is not None else None, t) for b, t in _FALLBACK_BAREME_IRPP]
#Calcul du taux horaire
    policy = PayrollPolicy.get_solo()
    heures_prevues = heures_prevues_mois(employee, year, month)

    # --- Taux horaire, selon la méthode configurée  ---
    if hourly_rate_override is not None:
        hourly_rate = Decimal(hourly_rate_override)
    elif policy.hourly_rate_method == PayrollPolicy.HourlyRateMethod.FORFAIT_MENSUEL_FIXE:
        hourly_rate = (base / Decimal(policy.fixed_monthly_hours)) if policy.fixed_monthly_hours else Decimal("0")
    elif policy.hourly_rate_method == PayrollPolicy.HourlyRateMethod.PERSONNALISEE:
        # Méthode personnalisée : à fournir explicitement via hourly_rate_override
        # (aucune formule spécifique n'étant définie dans le cahier des charges).
        # Repli sur la méthode au prorata pour ne jamais renvoyer un taux nul.
        hourly_rate = (base / heures_prevues) if heures_prevues else Decimal("0")
    else:  # PRORATA_HEURES_PREVUES (défaut)
        hourly_rate = (base / heures_prevues) if heures_prevues else Decimal("0")
    hourly_rate = hourly_rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    # --- Heures travaillées / supplémentaires ---
    overtime = compute_overtime_hours(employee, year, month)
    heures_travaillees = overtime["total_worked_hours"]

    montant_tier1 = (overtime["overtime_tier1_hours"] * hourly_rate * (Decimal("1") + policy.overtime_rate_1 / Decimal("100")))
    montant_tier2 = (overtime["overtime_tier2_hours"] * hourly_rate * (Decimal("1") + policy.overtime_rate_2 / Decimal("100")))
    montant_ferie = (overtime["holiday_hours"] * hourly_rate * (Decimal("1") + policy.holiday_rate / Decimal("100")))
    montant_repos = Decimal("0")
    if policy.rest_day_policy == PayrollPolicy.RestDayPolicy.SPECIAL_RATE:
        montant_repos = (overtime["rest_day_hours"] * hourly_rate * (Decimal("1") + policy.rest_day_rate / Decimal("100")))
    # rest_day_policy == TIME_OFF_IN_LIEU -> overtime["recoverable_hours"] : pas de montant, compensé en repos.

    heures_sup_total = overtime["overtime_tier1_hours"] + overtime["overtime_tier2_hours"]
    montant_heures_sup = (montant_tier1 + montant_tier2 + montant_ferie + montant_repos).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )

    # Alerte limite interne  — uniquement lors d'une génération réelle,
    # pas lors d'un simple aperçu (salary_detail), pour ne pas spammer la RH.
    if notify_overtime_alerts and overtime["weekly_alerts"]:
        _notify_internal_overtime_limit(employee, overtime["weekly_alerts"])

    # --- Absences (§7) ---
    absence = compute_absence_deduction(employee, year, month, hourly_rate)
    retenue_absences = absence["deduction_amount"]
#Calcul final : brut → net
    salaire_brut = base + autres_primes + prime_presence + indemnite_transport + montant_heures_sup

    cnss = (salaire_brut * taux_cnss).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    base_imposable = salaire_brut - cnss
    irpp = _irpp_annuel(base_imposable * 12, bareme_irpp) / 12
    irpp = irpp.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    css = (base_imposable * taux_css).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

    total_retenues = cnss + irpp + css + retenue_absences
    salaire_net = salaire_brut - total_retenues

    if hors_contrat:
        # Filet de sécurité final : même si une valeur intermédiaire avait
        # échappé aux zérotages ci-dessus, on garantit qu'AUCUN montant ne
        # sort pour un mois hors de toute période contractuelle.
        salaire_brut = Decimal("0")
        cnss = irpp = css = retenue_absences = total_retenues = salaire_net = Decimal("0")
        montant_heures_sup = Decimal("0")

    return {
        "employeur": settings.COMPANY_INFO["nom"],
        "matricule_fiscal": settings.COMPANY_INFO["matricule_fiscal"],
        "cnss_employeur": settings.COMPANY_INFO["cnss"],
        "adresse_employeur": settings.COMPANY_INFO["adresse"],
        "salarie": employee.full_name,
        "matricule": employee.matricule,
        "poste": employee.job_title,
        "departement": str(employee.department) if employee.department else "",
        "periode": f"{month:02d}/{year}",
        "mois_annee": _mois_libelle(month, year),
        "hors_contrat": hors_contrat,
        "salaire_base": base,
        "prime_presence": prime_presence,
        "indemnite_transport": indemnite_transport,
        "autres_primes": autres_primes,
        "heures_sup": heures_sup_total,
        "montant_heures_sup": montant_heures_sup,
        "salaire_brut": salaire_brut,
        "cnss": cnss,
        "irpp": irpp,
        "css": css,
        "retenue_absences": retenue_absences,
        "total_retenues": total_retenues,
        "salaire_net": salaire_net,
        "date_paiement": date.today(),
        "mode_paiement": salary.get_payment_mode_display(),
        "banque": salary.bank_name or "—",
        "devise": salary.currency,
        "rate_set": rate_set,
        # --- Détail heures (nouveau, étape 7) : utilisé pour le snapshot
        # figé de PayslipRecord et pour un futur affichage détaillé. ---
        "heures_prevues": heures_prevues,
        "heures_travaillees": heures_travaillees,
        "taux_horaire": hourly_rate,
        "heures_normales": overtime["normal_hours"],
        "heures_sup_tier1": overtime["overtime_tier1_hours"],
        "heures_sup_tier2": overtime["overtime_tier2_hours"],
        "heures_jour_ferie": overtime["holiday_hours"],
        "heures_jour_repos": overtime["rest_day_hours"],
        "heures_a_recuperer_travail": overtime["recoverable_hours"],
        "heures_a_recuperer_absence": absence["recoverable_hours"],
        "heures_absence_non_deduites": absence["no_deduction_hours"],
        "absence_details": absence["details"],
        "alertes_heures_sup": overtime["weekly_alerts"],
    }


def _notify_internal_overtime_limit(employee, weekly_alerts):
    """Notifie la RH (et le manager) qu'un employé a dépassé la limite
    interne d'heures supplémentaires sur au moins une semaine du mois (§8).
    Purement informatif : n'empêche jamais la génération de la paie."""
    from accounts.models import User
    from notifications.models import Notification
    from notifications.emailing import send_notification_email

    semaines = ", ".join(
        f"{a['week_start']:%d/%m}–{a['week_end']:%d/%m} ({a['overtime_hours']}h, limite {a['limit_hours']}h)"
        for a in weekly_alerts
    )
    message = (
        f"{employee} a dépassé la limite interne d'heures supplémentaires sur : {semaines}. "
        f"Une validation RH est recommandée avant application définitive."
    )

    destinataires = set(User.objects.filter(role__in=[User.Role.RH, User.Role.ADMIN]))
    if employee.manager:
        destinataires.add(employee.manager.user)

    for user in destinataires:
        notif = Notification.objects.create(
            recipient=user,
            category=Notification.Category.OTHER,
            title="Dépassement de la limite interne d'heures sup.",
            message=message,
            link=f"/paie/{employee.pk}/",
        )
        send_notification_email(notif)


_MOIS_FR = [
    "", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]


def _mois_libelle(month, year):
    return f"{_MOIS_FR[month]} {year}"