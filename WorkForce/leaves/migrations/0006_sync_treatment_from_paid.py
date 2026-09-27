from django.db import migrations


def sync_treatment_from_paid(apps, schema_editor):
    """Migration de données : paid=True -> NO_DEDUCTION, paid=False -> DEDUCTIBLE.

    Le champ `paid` est conservé tel quel pour compatibilité ; `treatment`
    devient la source utilisée par le module de paie.
    """
    LeaveType = apps.get_model("leaves", "LeaveType")
    LeaveType.objects.filter(paid=True).update(treatment="NO_DEDUCTION")
    LeaveType.objects.filter(paid=False).update(treatment="DEDUCTIBLE")


def reverse_noop(apps, schema_editor):
    # Rien à défaire : `paid` n'a jamais été modifié par cette migration.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("leaves", "0005_authorization_treatment_leavetype_treatment_and_more"),
    ]

    operations = [
        migrations.RunPython(sync_treatment_from_paid, reverse_noop),
    ]
