from decimal import Decimal

from django import forms
from django.forms import inlineformset_factory
from .models import SalaryHistory, SalaryIncreaseProposal, PayrollRateSet, PayrollRateBracket, PayrollPolicy, PublicHoliday


class RaiseForm(forms.Form):
    """Ajustement direct par la Paie (correction, hors circuit formel)."""
    increase_type = forms.ChoiceField(
        label="Type d'augmentation", choices=SalaryHistory.IncreaseType.choices,
        widget=forms.Select(attrs={"class": "td-input", "id": "id_increase_type"}),
    )
    value = forms.DecimalField(
        label="Valeur (% ou montant fixe selon le type)", max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "td-input"})
    )
    effective_date = forms.DateField(
        label="Date d'effet",
        widget=forms.DateInput(attrs={"type": "date", "class": "td-input"})
    )
    reason = forms.CharField(
        label="Motif", required=False,
        widget=forms.TextInput(attrs={"class": "td-input", "placeholder": "Ex : correction administrative..."})
    )


class SalaryEditForm(forms.ModelForm):
    class Meta:
        from .models import Salary
        model = Salary
        fields = ["base_amount", "bonus", "benefits", "presence_bonus", "transport_allowance", "payment_mode", "bank_name", "currency"]
        widgets = {
            "base_amount": forms.NumberInput(attrs={"class": "td-input"}),
            "bonus": forms.NumberInput(attrs={"class": "td-input"}),
            "benefits": forms.NumberInput(attrs={"class": "td-input"}),
            "presence_bonus": forms.NumberInput(attrs={"class": "td-input"}),
            "transport_allowance": forms.NumberInput(attrs={"class": "td-input"}),
            "payment_mode": forms.Select(attrs={"class": "td-input"}),
            "bank_name": forms.TextInput(attrs={"class": "td-input"}),
            "currency": forms.TextInput(attrs={"class": "td-input"}),
        }


class SalaryProposalForm(forms.Form):
    """Formulaire du Manager pour proposer une augmentation. On saisit soit
    un pourcentage, soit un nouveau salaire cible ; le formulaire calcule
    l'autre valeur automatiquement (voir clean())."""
    motif = forms.ChoiceField(
        label="Motif principal", choices=SalaryIncreaseProposal.Motif.choices,
        widget=forms.Select(attrs={"class": "td-input"}),
    )
    increase_type = forms.ChoiceField(
        label="Type d'augmentation", choices=SalaryHistory.IncreaseType.choices,
        widget=forms.Select(attrs={"class": "td-input"}),
    )
    value = forms.DecimalField(
        label="Valeur (% si Pourcentage, ou nouveau salaire si Montant fixe)",
        max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={"class": "td-input"}),
    )
    effective_date = forms.DateField(
        label="Date d'effet souhaitée",
        widget=forms.DateInput(attrs={"type": "date", "class": "td-input"}),
    )
    reason = forms.CharField(
        label="Justification détaillée", required=False,
        widget=forms.Textarea(attrs={
            "class": "td-input", "rows": 3,
            "placeholder": "Ex : objectifs atteints, très bonne évaluation annuelle, 2 ans d'ancienneté, nouvelles responsabilités de gestion d'équipe...",
        }),
    )

    def compute(self, current_salary):
        """Renvoie (proposed_salary, increase_percentage) à partir du salaire actuel."""
        current_salary = Decimal(current_salary)
        increase_type = self.cleaned_data["increase_type"]
        value = self.cleaned_data["value"]
        if increase_type == SalaryHistory.IncreaseType.PERCENTAGE:
            proposed = (current_salary * (Decimal("1") + value / Decimal("100"))).quantize(Decimal("0.01"))
            percentage = value
        else:
            proposed = value
            percentage = ((proposed - current_salary) / current_salary * 100) if current_salary else Decimal("0")
        return proposed, round(percentage, 2)


class SalaryProposalNewForm(SalaryProposalForm):
    """Variante avec sélection de l'employé (page « Propositions »)."""
    employee = forms.ModelChoiceField(
        label="Employé", queryset=None,
        widget=forms.Select(attrs={"class": "td-input"}),
    )

    field_order = ["employee", "motif", "increase_type", "value", "effective_date", "reason"]

    def __init__(self, *args, employee_queryset=None, **kwargs):
        super().__init__(*args, **kwargs)
        from employees.models import Employee
        self.fields["employee"].queryset = employee_queryset if employee_queryset is not None else Employee.objects.filter(status="ACTIVE")
        self.order_fields(self.field_order)


class ProposalDecisionForm(forms.Form):
    """Formulaire générique de rejet (RH ou Direction) — motif obligatoire."""
    note = forms.CharField(
        label="Motif du rejet", widget=forms.Textarea(attrs={"class": "td-input", "rows": 3}),
    )


class ProposalValidateForm(forms.Form):
    """Validation RH — note facultative (traçabilité)."""
    note = forms.CharField(
        label="Commentaire (facultatif)", required=False,
        widget=forms.Textarea(attrs={"class": "td-input", "rows": 2}),
    )


class PayrollRateSetForm(forms.ModelForm):
    """Création d'un nouveau barème de cotisations — réservé à la Paie
    (strict_role_required("PAYROLL")). RH/Direction/Admin le consultent
    en lecture seule."""
    class Meta:
        model = PayrollRateSet
        fields = ["effective_date", "cnss_rate", "css_rate", "reference"]
        widgets = {
            "effective_date": forms.DateInput(attrs={"type": "date", "class": "td-input"}),
            "cnss_rate": forms.NumberInput(attrs={"class": "td-input", "step": "0.0001"}),
            "css_rate": forms.NumberInput(attrs={"class": "td-input", "step": "0.0001"}),
            "reference": forms.TextInput(attrs={"class": "td-input", "placeholder": "Ex : Loi de Finances 2027, art. X"}),
        }


PayrollRateBracketFormSet = inlineformset_factory(
    PayrollRateSet, PayrollRateBracket,
    fields=["upper_bound", "rate", "order"],
    widgets={
        "upper_bound": forms.NumberInput(attrs={"class": "td-input", "placeholder": "vide = illimité"}),
        "rate": forms.NumberInput(attrs={"class": "td-input", "step": "0.01"}),
        "order": forms.NumberInput(attrs={"class": "td-input", "style": "width:70px;"}),
    },
    extra=3, can_delete=True,
)


class PayrollPolicyForm(forms.ModelForm):
    """Réglages configurables du calcul des heures supplémentaires et du
    taux horaire (§3, 5, 6, 7 des précisions du client) — réservé à la Paie."""

    class Meta:
        model = PayrollPolicy
        fields = [
            "hourly_rate_method", "fixed_monthly_hours",
            "overtime_rate_1", "overtime_tier2_threshold_hours", "overtime_rate_2",
            "holiday_rate", "rest_day_policy", "rest_day_rate",
            "internal_weekly_overtime_limit_percent",
        ]
        widgets = {
            "hourly_rate_method": forms.Select(attrs={"class": "td-input"}),
            "fixed_monthly_hours": forms.NumberInput(attrs={"class": "td-input", "step": "0.01"}),
            "overtime_rate_1": forms.NumberInput(attrs={"class": "td-input", "step": "0.01"}),
            "overtime_tier2_threshold_hours": forms.NumberInput(attrs={"class": "td-input", "step": "0.01"}),
            "overtime_rate_2": forms.NumberInput(attrs={"class": "td-input", "step": "0.01"}),
            "holiday_rate": forms.NumberInput(attrs={"class": "td-input", "step": "0.01"}),
            "rest_day_policy": forms.Select(attrs={"class": "td-input"}),
            "rest_day_rate": forms.NumberInput(attrs={"class": "td-input", "step": "0.01"}),
            "internal_weekly_overtime_limit_percent": forms.NumberInput(attrs={"class": "td-input", "step": "0.01"}),
        }


class PublicHolidayForm(forms.ModelForm):
    class Meta:
        model = PublicHoliday
        fields = ["date", "label"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date", "class": "td-input"}),
            "label": forms.TextInput(attrs={"class": "td-input", "placeholder": "Ex : Fête de l'Indépendance"}),
        }