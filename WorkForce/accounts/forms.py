from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordResetForm, SetPasswordForm


class WorkforceLoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={"class": "td-input", "placeholder": "Nom d'utilisateur", "autofocus": True})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"class": "td-input", "placeholder": "Mot de passe"})
    )


class WorkforcePasswordResetForm(PasswordResetForm):
    """Formulaire « mot de passe oublié » : reprend le style visuel de
    l'application (classe .td-input) sur le champ email.

    Choix assumé (application interne à effectif limité, pas un site
    public) : on affiche EXPLICITEMENT si l'email ne correspond à aucun
    compte, plutôt que le message neutre habituel « email envoyé » utilisé
    par défaut par Django pour éviter toute fuite d'information sur les
    comptes existants. Ce comportement par défaut reste plus sûr pour un
    site grand public ; ici, on privilégie la clarté pour l'utilisateur."""

    email = forms.EmailField(
        label="Adresse email",
        widget=forms.EmailInput(attrs={"class": "td-input", "placeholder": "vous@exemple.com", "autofocus": True}),
    )

    def clean_email(self):
        from django.contrib.auth import get_user_model
        email = self.cleaned_data["email"]
        User = get_user_model()
        if not User.objects.filter(email__iexact=email, is_active=True).exists():
            raise forms.ValidationError("Aucun compte actif n'est associé à cette adresse email.")
        return email


class WorkforceSetPasswordForm(SetPasswordForm):
    """Formulaire de saisie du nouveau mot de passe (lien reçu par email),
    avec le style visuel de l'application."""
    new_password1 = forms.CharField(
        label="Nouveau mot de passe",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "td-input", "autocomplete": "new-password"}),
    )
    new_password2 = forms.CharField(
        label="Confirmer le nouveau mot de passe",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "td-input", "autocomplete": "new-password"}),
    )