from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import Attendance, AbsenceAlert, PosteAutorise

@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "check_in", "check_out", "status", "lieu")
    list_filter = ("status", "lieu", "date")


@admin.register(AbsenceAlert)
class AbsenceAlertAdmin(admin.ModelAdmin):
    list_display = ("employee", "date", "kind", "justified", "treatment", "resolved", "created_at")
    list_filter = ("resolved", "justified", "kind")


@admin.register(PosteAutorise)
class PosteAutoriseAdmin(admin.ModelAdmin):
    list_display = ("nom", "actif", "derniere_utilisation", "ip_derniere_connexion", "lien_enregistrement")
    list_filter = ("actif",)
    readonly_fields = ("cookie_secret", "date_enregistrement", "lien_enregistrement")

    def lien_enregistrement(self, obj):
        if not obj.pk:
            return "-"
        url = reverse("attendance:enregistrer_poste", args=[obj.pk])
        return format_html(
            '<a href="{}" target="_blank">Ouvrir ce lien SUR le PC du bureau</a>', url
        )
    lien_enregistrement.short_description = "Lien d'enregistrement du poste"



