from django.db import migrations


def set_reduces_annual_balance(apps, schema_editor):
    """Migration de donnees raisonnable (best-effort) : seul le conge annuel
    doit reduire le solde annuel par defaut ; tout le reste reste a False
    (deja la valeur par defaut du champ). Reconnaissance par mot-cle sur le
    nom existant du LeaveType - a verifier manuellement par la RH si les
    intitules reels different de ceux du tableau fourni."""
    LeaveType = apps.get_model("leaves", "LeaveType")
    for lt in LeaveType.objects.all():
        name_lower = lt.name.lower()
        if "annuel" in name_lower or "annual" in name_lower:
            lt.reduces_annual_balance = True
            lt.save(update_fields=["reduces_annual_balance"])
        # Tous les autres types (maladie, maternite, paternite, sans solde,
        # formation, mission, exceptionnel...) restent a False, conformement
        # au tableau fourni par le client : seul le conge annuel reduit le solde.


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("leaves", "0007_leavetype_reduces_annual_balance_and_more"),
    ]

    operations = [
        migrations.RunPython(set_reduces_annual_balance, reverse_noop),
    ]
