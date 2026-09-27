"""
Supprime les fiches de pointage (Attendance) — et les alertes d'absence
liées — situées sur une date où l'employé n'avait AUCUN contrat couvrant
cette date (avant le début du premier contrat, après la fin d'un contrat,
trou entre deux contrats...).

Par défaut : SIMULATION uniquement (rien n'est supprimé, juste affiché).
Ajoutez --apply pour supprimer réellement.

Usage (depuis le dossier WorkForce) :
    # Voir ce qui serait supprimé, pour TOUS les employés
    python manage.py nettoyer_presences_hors_contrat

    # Voir ce qui serait supprimé, pour UN employé précis (ID visible
    # dans l'URL de sa fiche, ex: /paie/6/ -> --employee 6)
    python manage.py nettoyer_presences_hors_contrat --employee 6

    # Supprimer réellement (tous les employés concernés)
    python manage.py nettoyer_presences_hors_contrat --apply

    # Supprimer réellement (un seul employé)
    python manage.py nettoyer_presences_hors_contrat --employee 6 --apply
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from attendance.models import Attendance, AbsenceAlert
from employees.models import Contract


class Command(BaseCommand):
    help = "Supprime les pointages situés en dehors de toute période de contrat actif (simulation par défaut)."

    def add_arguments(self, parser):
        parser.add_argument("--employee", type=int, default=None, help="ID de l'employé à traiter (sinon : tous)")
        parser.add_argument("--apply", action="store_true", help="Applique réellement la suppression (sinon : simulation)")

    def handle(self, *args, **options):
        employee_id = options.get("employee")
        apply_changes = options.get("apply")

        qs = Attendance.objects.select_related("employee").order_by("employee_id", "date")
        if employee_id:
            qs = qs.filter(employee_id=employee_id)

        a_supprimer = []
        for att in qs:
            couvert = Contract.objects.filter(
                employee=att.employee, start_date__lte=att.date
            ).filter(Q(end_date__isnull=True) | Q(end_date__gte=att.date)).exists()
            if not couvert:
                a_supprimer.append(att)

        if not a_supprimer:
            self.stdout.write(self.style.SUCCESS("Aucune fiche de pointage hors contrat trouvée."))
            return

        self.stdout.write(f"{len(a_supprimer)} fiche(s) de pointage hors contrat trouvée(s) :")
        for att in a_supprimer:
            self.stdout.write(f"  - {att.employee} — {att.date} ({att.get_status_display()})")

        if not apply_changes:
            self.stdout.write(self.style.WARNING(
                "\nSimulation seulement, rien n'a été supprimé. "
                "Relancez avec --apply pour supprimer réellement."
            ))
            return

        total_alertes = 0
        for att in a_supprimer:
            deleted, _ = AbsenceAlert.objects.filter(employee=att.employee, date=att.date).delete()
            total_alertes += deleted

        ids = [a.id for a in a_supprimer]
        total_pointages, _ = Attendance.objects.filter(id__in=ids).delete()

        self.stdout.write(self.style.SUCCESS(
            f"\n{total_pointages} fiche(s) de pointage supprimée(s), "
            f"{total_alertes} alerte(s) d'absence liée(s) supprimée(s)."
        ))
