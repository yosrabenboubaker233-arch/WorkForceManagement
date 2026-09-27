from datetime import date, timedelta

from django import forms
from django.conf import settings

from .models import LeaveRequest, Authorization

DELAI_PREAVIS_JOURS = getattr(settings, "LEAVE_PREAVIS_JOURS", 2)


class LeaveRequestForm(forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = ["leave_type", "start_date", "end_date", "reason", "attachment"]
        widgets = {
            "leave_type": forms.Select(attrs={"class": "td-input"}),
            "start_date": forms.DateInput(attrs={"type": "date", "class": "td-input"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "td-input"}),
            "reason": forms.Textarea(attrs={"class": "td-input", "rows": 3, "placeholder": "Précisez le motif (optionnel)"}),
            "attachment": forms.ClearableFileInput(attrs={"class": "td-input"}),
        }

    def __init__(self, *args, employee=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.employee = employee
        date_min = (date.today() + timedelta(days=DELAI_PREAVIS_JOURS)).isoformat()
        self.fields["start_date"].widget.attrs["min"] = date_min
        self.fields["end_date"].widget.attrs["min"] = date_min

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        leave_type = cleaned.get("leave_type")

        if start and end and end < start:
            raise forms.ValidationError("La date de fin doit être postérieure à la date de début.")

        # Préavis obligatoire (cahier des charges §5) : la date de début doit
        # être au moins DELAI_PREAVIS_JOURS jours après aujourd'hui.
        if start:
            date_limite = date.today() + timedelta(days=DELAI_PREAVIS_JOURS)
            if start < date_limite:
                raise forms.ValidationError(
                    f"Le délai de préavis est de {DELAI_PREAVIS_JOURS} jours minimum : "
                    f"la date de début la plus proche possible est le {date_limite.strftime('%d/%m/%Y')}."
                )

        # Solde de congés suffisant : uniquement pour les types de congé qui
        # impactent le solde annuel (LeaveType.reduces_annual_balance).
        if start and end and leave_type and leave_type.reduces_annual_balance and self.employee is not None:
            nb_jours_demandes = (end - start).days + 1
            solde = self.employee.leave_balance_days
            if nb_jours_demandes > solde:
                raise forms.ValidationError(
                    f"Solde de congés insuffisant : cette demande représente {nb_jours_demandes} jour(s), "
                    f"mais il ne vous reste que {solde} jour(s) disponible(s)."
                )
        return cleaned


class DecisionForm(forms.Form):
    """Formulaire de décision générique (étape 1 ou étape 2), réutilisé pour
    les congés et les autorisations. Le commentaire est obligatoire en cas
    de refus — vérifié dans la vue, pas ici, car la règle dépend de l'action
    (approve/reject) transmise dans l'URL."""
    comment = forms.CharField(
        required=False, label="Commentaire",
        widget=forms.Textarea(attrs={
            "class": "td-input", "rows": 2,
            "placeholder": "Motif (obligatoire en cas de refus)"
        }),
    )


class AuthorizationForm(forms.ModelForm):
    class Meta:
        model = Authorization
        fields = ["kind", "date", "start_time", "end_time", "reason"]
        widgets = {
            "kind": forms.Select(attrs={"class": "td-input"}),
            "date": forms.DateInput(attrs={"type": "date", "class": "td-input"}),
            "start_time": forms.TimeInput(attrs={"type": "time", "class": "td-input"}),
            "end_time": forms.TimeInput(attrs={"type": "time", "class": "td-input"}),
            "reason": forms.TextInput(attrs={"class": "td-input", "placeholder": "Ex : rendez-vous médical"}),
        }

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_time"), cleaned.get("end_time")
        if start and end and end <= start:
            raise forms.ValidationError("L'heure de fin doit être postérieure à l'heure de début.")
        return cleaned


class AuthorizationTreatmentForm(forms.ModelForm):
    """Réservé à la RH/Paie : ajuste l'impact paie d'une autorisation déjà
    décidée (ex : requalifier en heures à récupérer, §7)."""
    class Meta:
        model = Authorization
        fields = ["treatment"]
        widgets = {"treatment": forms.Select(attrs={"class": "td-input"})}