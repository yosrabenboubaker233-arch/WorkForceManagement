"""
Circuit de validation à étapes, partagé par les congés ET les autorisations
d'absence (cahier des charges v4).

Règle : l'étape 1 dépend du RÔLE du demandeur, l'étape 2 (RH) n'existe que
pour les demandeurs Employé/Manager. La Paie n'est jamais approbatrice :
elle est seulement informée une fois la demande définitivement APPROUVÉE.

    Employé   -> Manager (étape 1) -> RH (étape 2) -> Paie informée
    Manager   -> Direction (étape 1) -> RH (étape 2) -> Paie informée
    RH        -> Direction (étape 1) -> (pas d'étape 2) -> Paie informée
    Paie      -> Direction (étape 1) -> (pas d'étape 2) -> Paie informée
    Admin     -> Direction (étape 1) -> (pas d'étape 2) -> Paie informée

Toute classe qui veut bénéficier de ce circuit (LeaveRequest, Authorization)
hérite de `WorkflowMixin` (modèle abstrait) et implémente juste ses propres
champs métier (dates, motif...).
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import User

# Rôles dont la demande passe par le Manager direct en étape 1
STEP1_VIA_MANAGER_ROLES = {User.Role.EMPLOYEE}

# Rôles dont la demande nécessite une validation RH en étape 2
STEP2_REQUIRED_ROLES = {User.Role.EMPLOYEE, User.Role.MANAGER}


class WorkflowMixin(models.Model):
    class Status(models.TextChoices):
        PENDING_STEP1 = "PENDING_STEP1", "En attente (étape 1)"
        PENDING_STEP2 = "PENDING_STEP2", "En attente (validation RH)"
        APPROVED = "APPROVED", "Approuvée"
        REJECTED = "REJECTED", "Refusée"
        CANCELLED = "CANCELLED", "Annulée"
        EXPIRED = "EXPIRED", "Expirée (date passée sans décision)"

    class PayrollStatus(models.TextChoices):
        NOT_APPLICABLE = "NOT_APPLICABLE", "—"
        TO_PROCESS = "TO_PROCESS", "À traiter"
        PROCESSED = "PROCESSED", "Traité"

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_STEP1)

    step1_role = models.CharField(
        "Approbateur étape 1", max_length=12,
        choices=[("MANAGER", "Manager"), ("DIRECTION", "Direction Générale")],
        default="MANAGER",
    )
    step2_required = models.BooleanField("Validation RH requise", default=True)

    step1_decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    step1_decided_at = models.DateTimeField(null=True, blank=True)
    step1_comment = models.TextField("Commentaire étape 1", blank=True)

    step2_decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    step2_decided_at = models.DateTimeField(null=True, blank=True)
    step2_comment = models.TextField("Commentaire RH", blank=True)

    payroll_status = models.CharField(
        "Statut Paie", max_length=15, choices=PayrollStatus.choices, default=PayrollStatus.NOT_APPLICABLE
    )
    payroll_processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    payroll_processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    # ------------------------------------------------------------------
    # Initialisation du circuit selon le rôle du demandeur
    # ------------------------------------------------------------------
    def init_workflow(self):
        role = self.employee.user.role
        if role in STEP1_VIA_MANAGER_ROLES and self.employee.manager:
            self.step1_role = "MANAGER"
        else:
            # Pas de manager direct (ex: le manager lui-même, RH, Paie, Admin,
            # ou un employé sans manager assigné) -> la Direction tranche.
            self.step1_role = "DIRECTION"
        self.step2_required = role in STEP2_REQUIRED_ROLES
        self.status = self.Status.PENDING_STEP1

    # ------------------------------------------------------------------
    # Destinataires de chaque étape (pour les notifications + boîtes de validation)
    # ------------------------------------------------------------------
    def step1_recipients(self):
        if self.step1_role == "MANAGER" and self.employee.manager:
            return [self.employee.manager.user]
        return list(User.objects.filter(role=User.Role.DIRECTION))

    def step2_recipients(self):
        return list(User.objects.filter(role=User.Role.RH))

    def payroll_recipients(self):
        return list(User.objects.filter(role=User.Role.PAYROLL))

    # ------------------------------------------------------------------
    # Décisions
    # ------------------------------------------------------------------
    def apply_step1_decision(self, approved, user, comment=""):
        self.step1_decided_by = user
        self.step1_decided_at = timezone.now()
        self.step1_comment = comment
        if not approved:
            self.status = self.Status.REJECTED
        elif self.step2_required:
            self.status = self.Status.PENDING_STEP2
        else:
            self._mark_approved()
        self.save()

    def apply_step2_decision(self, approved, user, comment=""):
        self.step2_decided_by = user
        self.step2_decided_at = timezone.now()
        self.step2_comment = comment
        if approved:
            self._mark_approved()
        else:
            self.status = self.Status.REJECTED
        self.save()

    def _mark_approved(self):
        self.status = self.Status.APPROVED
        self.payroll_status = self.PayrollStatus.TO_PROCESS

    def mark_payroll_processed(self, user):
        self.payroll_status = self.PayrollStatus.PROCESSED
        self.payroll_processed_by = user
        self.payroll_processed_at = timezone.now()
        self.save(update_fields=["payroll_status", "payroll_processed_by", "payroll_processed_at"])

    def mark_expired(self):
        """Marque la demande comme expirée : sa date est passée sans qu'une
        décision (accepter/refuser) n'ait été prise à temps. Une demande
        expirée ne peut plus être approuvée ni refusée."""
        self.status = self.Status.EXPIRED
        self.save(update_fields=["status"])
        
    @property
    def step1_label(self):
        return "Direction Générale" if self.step1_role == "DIRECTION" else "Manager"
