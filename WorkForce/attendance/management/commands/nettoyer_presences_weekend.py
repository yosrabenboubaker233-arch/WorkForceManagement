"""
Supprime les fiches de pointage (Attendance) — et les alertes d'absence
liées — enregistrées un samedi ou un dimanche (jours normalement non
travaillés).

Par défaut : SIMULATION uniquement (rien n'est supprimé, juste affiché).
Ajoutez --apply pour supprimer réellement.

Usage (depuis le dossier WorkForce) :
    # Voir ce qui serait supprimé, pour TOUS les employés
    python manage.py nettoyer_presences_weekend

    # Voir ce qui serait supprimé, pour UN employé précis (ID visible
    # dans l'URL de sa fiche, ex: /paie/6/ -> --employee 6)
    python manage.py nettoyer_presences_weekend --employee 6

    # Supprimer réellement (tous les employés concernés)
    python manage.py nettoyer_presences_weekend --apply

    # Supprimer réellement (un seul employé)
    python manage.py nettoyer_presences_weekend --employee 6 --apply
"""
from django.core.management.base import BaseCommand

from attendance.models import Attendance, AbsenceAlert


class Command(BaseCommand):
    help = "Supprime les pointages enregistrés un samedi ou un dimanche (simulation par défaut)."

    def add_arguments(self, parser):
        parser.add_argument("--employee", type=int, default=None, help="ID de l'employé à traiter (sinon : tous)")
        parser.add_argument("--apply", action="store_true", help="Applique réellement la suppression (sinon : simulation)")

    def handle(self, *args, **options):
        employee_id = options.get("employee")
        apply_changes = options.get("apply")

        qs = Attendance.objects.select_related("employee").order_by("employee_id", "date")
        if employee_id:
            qs = qs.filter(employee_id=employee_id)

        # isoweekday() : 6 = samedi, 7 = dimanche
        a_supprimer = [att for att in qs if att.date.isoweekday() in (6, 7)]

        if not a_supprimer:
            self.stdout.write(self.style.SUCCESS("Aucune fiche de pointage un samedi/dimanche trouvée."))
            return

        self.stdout.write(f"{len(a_supprimer)} fiche(s) de pointage un samedi/dimanche trouvée(s) :")
        jours_fr = {6: "samedi", 7: "dimanche"}
        for att in a_supprimer:
            self.stdout.write(
                f"  - {att.employee} — {att.date} ({jours_fr[att.date.isoweekday()]}) — {att.get_status_display()}"
            )

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
