"""
Commande sûre pour configurer le traitement paie et l'impact sur le solde
annuel des LeaveType RÉELLEMENT présents en base — sans toucher à aucune
autre donnée (salariés, contrats, congés pris, autorisations, pointages,
paies). Ne crée, ne supprime et ne renomme aucun LeaveType.

Usage :
    python manage.py set_leave_type_treatment
        -> affiche tous les LeaveType existants avec leurs valeurs actuelles,
           sans rien modifier.

    python manage.py set_leave_type_treatment "Congé annuel" \\
        --treatment NO_DEDUCTION --reduces-balance yes
        -> modifie UNIQUEMENT ces deux champs sur CE type précis.
"""
from django.core.management.base import BaseCommand, CommandError

from leaves.models import LeaveType, PayrollTreatment


class Command(BaseCommand):
    help = "Affiche ou modifie le traitement paie / impact solde annuel d'un LeaveType existant, sans toucher au reste."

    def add_arguments(self, parser):
        parser.add_argument("name", nargs="?", help="Nom exact du LeaveType à modifier (voir la liste sans argument).")
        parser.add_argument("--treatment", choices=[c[0] for c in PayrollTreatment.choices], help="Nouveau traitement paie.")
        parser.add_argument("--reduces-balance", choices=["yes", "no"], help="Réduit le solde de congé annuel ?")

    def handle(self, *args, **options):
        name = options.get("name")

        if not name:
            self.stdout.write("LeaveType existants en base (aucune modification) :\n")
            for lt in LeaveType.objects.all().order_by("name"):
                self.stdout.write(
                    f"  {lt.name!r:35s} paid={lt.paid!s:6s} "
                    f"treatment={lt.treatment:16s} reduces_annual_balance={lt.reduces_annual_balance}"
                )
            return

        try:
            lt = LeaveType.objects.get(name=name)
        except LeaveType.DoesNotExist:
            raise CommandError(
                f"Aucun LeaveType nommé exactement {name!r}. "
                f"Lancez 'python manage.py set_leave_type_treatment' sans argument pour voir les noms exacts."
            )

        updated = []
        if options.get("treatment"):
            lt.treatment = options["treatment"]
            updated.append("treatment")
        if options.get("reduces_balance") is not None:
            lt.reduces_annual_balance = options["reduces_balance"] == "yes"
            updated.append("reduces_annual_balance")

        if not updated:
            self.stdout.write(self.style.WARNING("Rien à modifier : précisez --treatment et/ou --reduces-balance."))
            return

        lt.save(update_fields=updated)
        self.stdout.write(self.style.SUCCESS(
            f"{lt.name} : treatment={lt.treatment}, reduces_annual_balance={lt.reduces_annual_balance} (mis à jour, rien d'autre touché)."
        ))
