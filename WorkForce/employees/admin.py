from django.contrib import admin
from .models import (
    Department, Employee, Document, WorkHistoryEntry, Contract,
    ContractAttributeDefinition, ContractAttributeValue,
)


@admin.register(ContractAttributeDefinition)
class ContractAttributeDefinitionAdmin(admin.ModelAdmin):
    """Ici, RH/Admin peuvent AJOUTER un nouveau champ au formulaire de
    contrat sans toucher au code : il apparaît automatiquement sur
    « Nouveau contrat » et « Modifier » dès qu'il est marqué Actif — mais
    UNIQUEMENT pour les contrats créés/modifiés à partir de maintenant ;
    les contrats déjà existants ne sont jamais impactés rétroactivement.

    Pour RETIRER un champ : décochez « Actif » (il disparaît du formulaire,
    les valeurs déjà saisies sur d'anciens contrats restent visibles sur
    leur fiche). La suppression pure (bouton Supprimer) est volontairement
    bloquée par Django tant qu'un contrat a une valeur enregistrée pour ce
    champ, justement pour ne jamais perdre l'historique des anciens
    contrats."""
    list_display = ("label", "name", "field_type", "required", "active", "order")
    list_editable = ("required", "active", "order")
    list_filter = ("field_type", "active")
    prepopulated_fields = {"name": ("label",)}


class ContractAttributeValueInline(admin.TabularInline):
    model = ContractAttributeValue
    extra = 0


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name",)


class DocumentInline(admin.TabularInline):
    model = Document
    extra = 0


class WorkHistoryInline(admin.TabularInline):
    model = WorkHistoryEntry
    extra = 0


class ContractInline(admin.TabularInline):
    model = Contract
    extra = 0
    fields = ("contract_number", "contract_type", "start_date", "end_date", "status")
    readonly_fields = ("contract_number",)


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ("full_name", "matricule", "job_title", "department", "manager", "status",
                     "hire_date", "leave_balance_days", "authorization_hours_carry")
    list_filter = ("department", "status")
    search_fields = ("user__first_name", "user__last_name", "job_title", "matricule")
    inlines = [ContractInline, DocumentInline, WorkHistoryInline]


@admin.register(WorkHistoryEntry)
class WorkHistoryAdmin(admin.ModelAdmin):
    list_display = ("employee", "kind", "title", "date")
    list_filter = ("kind",)


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ("contract_number", "employee", "contract_type", "start_date", "end_date", "status")
    list_filter = ("contract_type", "status", "work_time")
    search_fields = ("contract_number", "employee__user__first_name", "employee__user__last_name")
    inlines = [ContractAttributeValueInline]