from decimal import Decimal

from django import forms
from accounts.models import User
from .models import Employee, Document, WorkHistoryEntry, Contract


class MyProfileForm(forms.ModelForm):
    """Auto-édition par l'employé lui-même : identité, contact, photo, adresse.
    Volontairement SANS poste/service/salaire/contrat/date d'embauche/manager,
    réservés à la RH (cahier des charges v6 §7)."""

    first_name = forms.CharField(label="Prénom", widget=forms.TextInput(attrs={"class": "td-input"}))
    last_name = forms.CharField(label="Nom", widget=forms.TextInput(attrs={"class": "td-input"}))
    email = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"class": "td-input"}))
    phone = forms.CharField(label="Téléphone", required=False, widget=forms.TextInput(attrs={"class": "td-input"}))
    avatar = forms.ImageField(label="Photo", required=False, widget=forms.ClearableFileInput(attrs={"class": "td-input"}))

    class Meta:
        model = Employee
        fields = ["address"]
        widgets = {
            "address": forms.TextInput(attrs={"class": "td-input", "placeholder": "Adresse postale"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is not None:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["email"].initial = user.email
            self.fields["phone"].initial = user.phone

    def save(self, commit=True):
        employee = super().save(commit=False)
        if self.user is not None:
            self.user.first_name = self.cleaned_data["first_name"]
            self.user.last_name = self.cleaned_data["last_name"]
            self.user.email = self.cleaned_data["email"]
            self.user.phone = self.cleaned_data["phone"]
            if self.cleaned_data.get("avatar"):
                self.user.avatar = self.cleaned_data["avatar"]
            if commit:
                self.user.save()
        if commit:
            employee.save()
        return employee


class EmployeeCreationForm(forms.ModelForm):
    """Création complète d'un nouveau salarié : identité + compte de
    connexion + dossier RH, en un seul formulaire. Le nom d'utilisateur et
    le mot de passe sont générés automatiquement (voir accounts/utils.py)
    et envoyés par email à l'adresse saisie ici."""

    first_name = forms.CharField(label="Prénom", widget=forms.TextInput(attrs={"class": "td-input"}))
    last_name = forms.CharField(label="Nom", widget=forms.TextInput(attrs={"class": "td-input"}))
    email = forms.EmailField(
        label="Email personnel/professionnel",
        help_text="Les identifiants de connexion (nom d'utilisateur + mot de passe) seront envoyés à cette adresse.",
        widget=forms.EmailInput(attrs={"class": "td-input"}),
    )
    role = forms.ChoiceField(label="Rôle applicatif", choices=User.Role.choices, widget=forms.Select(attrs={"class": "td-input"}))

    class Meta:
        model = Employee
        fields = [
            "manager", "department", "job_title", "hire_date",
            "status", "weekly_hours", "leave_balance_days", "cv_file",
        ]
        widgets = {
            "hire_date": forms.DateInput(attrs={"type": "date", "class": "td-input"}),
            "manager": forms.Select(attrs={"class": "td-input"}),
            "department": forms.Select(attrs={"class": "td-input"}),
            "job_title": forms.TextInput(attrs={"class": "td-input"}),
            "status": forms.Select(attrs={"class": "td-input"}),
            "weekly_hours": forms.NumberInput(attrs={"class": "td-input"}),
            "leave_balance_days": forms.NumberInput(attrs={"class": "td-input"}),
            "cv_file": forms.ClearableFileInput(attrs={"class": "td-input"}),
        }

    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Un compte existe déjà avec cet email.")
        return email


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = [
            "manager", "department", "job_title", "hire_date",
            "status", "weekly_hours", "leave_balance_days", "cv_file",
        ]
        widgets = {
            "hire_date": forms.DateInput(attrs={"type": "date", "class": "td-input"}),
            "manager": forms.Select(attrs={"class": "td-input"}),
            "department": forms.Select(attrs={"class": "td-input"}),
            "job_title": forms.TextInput(attrs={"class": "td-input"}),
            "status": forms.Select(attrs={"class": "td-input"}),
            "weekly_hours": forms.NumberInput(attrs={"class": "td-input"}),
            "leave_balance_days": forms.NumberInput(attrs={"class": "td-input"}),
            "cv_file": forms.ClearableFileInput(attrs={"class": "td-input"}),
        }


class DocumentForm(forms.ModelForm):
    class Meta:
        model = Document
        fields = ["kind", "title", "file"]
        widgets = {
            "kind": forms.Select(attrs={"class": "td-input"}),
            "title": forms.TextInput(attrs={"class": "td-input", "placeholder": "Titre du document"}),
            "file": forms.ClearableFileInput(attrs={"class": "td-input"}),
        }


class WorkHistoryForm(forms.ModelForm):
    class Meta:
        model = WorkHistoryEntry
        fields = ["kind", "title", "description", "date"]
        widgets = {
            "kind": forms.Select(attrs={"class": "td-input"}),
            "title": forms.TextInput(attrs={"class": "td-input"}),
            "description": forms.Textarea(attrs={"class": "td-input", "rows": 3}),
            "date": forms.DateInput(attrs={"type": "date", "class": "td-input"}),
        }


class ContractForm(forms.ModelForm):
    WORK_DAY_CHOICES = [
        ("1", "Lundi"), ("2", "Mardi"), ("3", "Mercredi"), ("4", "Jeudi"),
        ("5", "Vendredi"), ("6", "Samedi"), ("7", "Dimanche"),
    ]

    work_days_choices = forms.MultipleChoiceField(
        label="Jours travaillés", choices=WORK_DAY_CHOICES, required=True,
        widget=forms.CheckboxSelectMultiple,
        help_text="Détermine les jours ouvrables du mois et distingue les jours de repos (ex : samedi).",
    )

    class Meta:
        model = Contract
        fields = [
            "contract_type", "start_date", "end_date", "job_title", "department",
            "base_salary", "bonuses", "work_time", "weekly_hours",
            "trial_period_end", "document",
        ]
        widgets = {
            "contract_type": forms.Select(attrs={"class": "td-input"}),
            "start_date": forms.DateInput(attrs={"type": "date", "class": "td-input"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "td-input"}),
            "job_title": forms.TextInput(attrs={"class": "td-input"}),
            "department": forms.Select(attrs={"class": "td-input"}),
            "base_salary": forms.NumberInput(attrs={"class": "td-input"}),
            "bonuses": forms.NumberInput(attrs={"class": "td-input"}),
            "work_time": forms.Select(attrs={"class": "td-input"}),
            "weekly_hours": forms.NumberInput(attrs={"class": "td-input", "step": "0.5"}),
            "trial_period_end": forms.DateInput(attrs={"type": "date", "class": "td-input"}),
            "document": forms.ClearableFileInput(attrs={"class": "td-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.work_days:
            self.fields["work_days_choices"].initial = self.instance.work_days.split(",")
        elif not self.instance.pk:
            self.fields["work_days_choices"].initial = ["1", "2", "3", "4", "5"]
        self.fields["weekly_hours"].help_text = (
            "Les heures/jour et les heures prévues du mois sont calculées "
            "AUTOMATIQUEMENT à partir de ce nombre et des jours travaillés "
            "cochés ci-dessous — ne les saisissez pas séparément."
        )

    def clean(self):
        cleaned = super().clean()
        contract_type = cleaned.get("contract_type")
        end_date = cleaned.get("end_date")
        if contract_type == "CDD" and not end_date:
            raise forms.ValidationError("La date de fin est obligatoire pour un CDD.")
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        selected_days = sorted(int(d) for d in self.cleaned_data["work_days_choices"])
        instance.work_days = ",".join(str(d) for d in selected_days)
        # « Heures / jour » n'est plus saisie séparément par la RH : elle est
        # dérivée AUTOMATIQUEMENT des heures/semaine réparties sur les jours
        # travaillés cochés, ce qui évite toute incohérence entre les deux
        # valeurs (ex : 40h/semaine mais 8h/jour laissé par défaut alors que
        # seuls 4 jours sont travaillés -> ne donnerait que 32h/semaine réelles).
        nb_jours = len(selected_days) or 1
        instance.hours_per_day = (Decimal(instance.weekly_hours) / Decimal(nb_jours)).quantize(Decimal("0.01"))
        if commit:
            instance.save()
        return instance


class ContractEndForm(forms.ModelForm):
    class Meta:
        model = Contract
        fields = ["end_reason"]
        widgets = {
            "end_reason": forms.Textarea(attrs={
                "class": "td-input", "rows": 3,
                "placeholder": "Ex : fin de CDD, démission, rupture négociée, promotion (nouveau contrat)..."
            }),
        }