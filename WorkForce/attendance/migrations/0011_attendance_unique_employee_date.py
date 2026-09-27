# Generated manually — corrige un doublon possible de pointage
# (employee, date) jamais empêché en base.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("attendance", "0010_attendance_rapport_teletravail"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="attendance",
            constraint=models.UniqueConstraint(
                fields=["employee", "date"], name="unique_attendance_par_employe_et_jour"
            ),
        ),
    ]
