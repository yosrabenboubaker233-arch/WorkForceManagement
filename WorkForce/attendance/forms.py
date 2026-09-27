from django import forms

from .models import AbsenceAlert


class AbsenceAlertResolveForm(forms.ModelForm):
    """Utilisé par la RH pour statuer sur une absence non couverte par un
    congé ou une autorisation (§7) : justifiée ou non, et impact paie."""
    class Meta:
        model = AbsenceAlert
        fields = ["justified", "treatment"]
        widgets = {
            "justified": forms.CheckboxInput(),
            "treatment": forms.Select(attrs={"class": "td-input"}),
        }
