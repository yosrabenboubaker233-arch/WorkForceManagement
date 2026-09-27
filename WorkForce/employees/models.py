from django.conf import settings
from django.db import models


class Department(models.Model):
    name = models.CharField("Service", max_length=100)

    def __str__(self):
        return self.name


class Employee(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Actif"
        INACTIVE = "INACTIVE", "Inactif"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="employee_profile"
    )
    manager = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="team_members", verbose_name="Manager direct"
    )
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, related_name="employees")
    job_title = models.CharField("Poste", max_length=120, blank=True)
    hire_date = models.DateField("Date d'embauche", null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    # Temps de travail
    weekly_hours = models.DecimalField("Heures contractuelles / semaine", max_digits=5, decimal_places=2, default=40)
    leave_balance_days = models.DecimalField(
        "Solde de congés (jours)", max_digits=5, decimal_places=1, default=26,
        help_text="Référence annuelle : 26 jours/an (voir settings.ANNUAL_LEAVE_DAYS).",
    )
    authorization_hours_carry = models.DecimalField(
        "Heures d'autorisation en report", max_digits=5, decimal_places=2, default=0,
        help_text="Heures d'autorisation approuvées cumulées, pas encore converties en jour de congé (report).",
    )
    last_accrual_month = models.CharField(
        "Dernier mois crédité (AAAA-MM)", max_length=7, blank=True,
        help_text="Rempli automatiquement par la commande accrue_leave_balance pour éviter un double crédit.",
    )

    cv_file = models.FileField("CV", upload_to="cv/", blank=True, null=True)
    address = models.CharField("Adresse", max_length=255, blank=True)

    class Meta:
        verbose_name = "Employé"
        verbose_name_plural = "Employés"

    def __str__(self):
        return self.user.get_full_name() or self.user.username

    @property
    def full_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def matricule(self):
        """Identifiant employé lisible pour les documents officiels (bulletin de paie...)."""
        return f"EMP{self.pk:04d}" if self.pk else "—"


class Document(models.Model):
    class Kind(models.TextChoices):
        CV = "CV", "CV"
        DIPLOMA = "DIPLOMA", "Diplôme"
        CONTRACT = "CONTRACT", "Contrat"
        OTHER = "OTHER", "Autre"

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="documents")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.OTHER)
    title = models.CharField(max_length=150)
    file = models.FileField(upload_to="documents/")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.employee})"


class WorkHistoryEntry(models.Model):
    class Kind(models.TextChoices):
        HIRE = "HIRE", "Embauche"
        PROMOTION = "PROMOTION", "Promotion"
        TRANSFER = "TRANSFER", "Mutation"
        EVALUATION = "EVALUATION", "Évaluation"
        TRAINING = "TRAINING", "Formation"

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="history")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    date = models.DateField()

    class Meta:
        ordering = ["-date"]
        verbose_name = "Historique"
        verbose_name_plural = "Historique"

    def __str__(self):
        return f"{self.get_kind_display()} — {self.employee} ({self.date})"


class Contract(models.Model):
    """Contrat de travail d'un employé — avec historique complet : un
    salarié peut avoir plusieurs contrats successifs dans le temps
    (Stage -> CDD -> CDI, changement de poste avec avenant, etc.).
    Un seul contrat doit normalement être « Actif » à la fois."""

    class ContractType(models.TextChoices):
        STAGE_PFE = "STAGE_PFE", "Stage PFE"
        STAGE = "STAGE", "Stage"
        CDD = "CDD", "CDD"
        CDI = "CDI", "CDI"

    class WorkTime(models.TextChoices):
        FULL_TIME = "FULL_TIME", "Temps plein"
        PART_TIME = "PART_TIME", "Temps partiel"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Actif"
        ENDED = "ENDED", "Terminé"
        SUSPENDED = "SUSPENDED", "Suspendu"

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="contracts")
    contract_number = models.CharField("Numéro de contrat", max_length=30, unique=True, blank=True)
    contract_type = models.CharField("Type de contrat", max_length=20, choices=ContractType.choices)
    start_date = models.DateField("Date de début")
    end_date = models.DateField("Date de fin (si CDD)", null=True, blank=True)
    job_title = models.CharField("Poste occupé", max_length=120)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, related_name="contracts")
    base_salary = models.DecimalField("Salaire de base", max_digits=10, decimal_places=2)
    bonuses = models.DecimalField("Prime(s)", max_digits=10, decimal_places=2, default=0)
    work_time = models.CharField("Temps de travail", max_length=15, choices=WorkTime.choices, default=WorkTime.FULL_TIME)
    weekly_hours = models.DecimalField(
        "Heures contractuelles / semaine", max_digits=5, decimal_places=2, default=40,
        help_text="Ex : 40.00 pour un temps plein classique.",
    )
    hours_per_day = models.DecimalField(
        "Heures / jour", max_digits=4, decimal_places=2, default=8,
        help_text="Ex : 8.00 heures par jour travaillé.",
    )
    work_days = models.CharField(
        "Jours travaillés", max_length=20, default="1,2,3,4,5",
        help_text="Jours de la semaine travaillés, séparés par des virgules (1=lundi ... 7=dimanche). Ex : 1,2,3,4,5 pour lundi-vendredi.",
    )
    trial_period_end = models.DateField("Fin de la période d'essai", null=True, blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.ACTIVE)
    end_reason = models.CharField("Motif de fin de contrat", max_length=255, blank=True)
    document = models.FileField("Document contractuel (PDF signé)", upload_to="contrats/", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]
        verbose_name = "Contrat"
        verbose_name_plural = "Contrats"

    def __str__(self):
        return f"{self.get_contract_type_display()} — {self.employee} ({self.start_date})"

    def save(self, *args, **kwargs):
        if not self.contract_number:
            last = Contract.objects.order_by("-id").first()
            next_number = (last.id + 1) if last else 1
            self.contract_number = f"CTR{next_number:05d}"
        super().save(*args, **kwargs)

    @property
    def is_trial_period_active(self):
        from django.utils import timezone
        return bool(self.trial_period_end and self.trial_period_end >= timezone.localdate())

    @property
    def work_days_list(self):
        """Jours travaillés sous forme de liste d'entiers ISO (1=lundi ... 7=dimanche)."""
        if not self.work_days:
            return [1, 2, 3, 4, 5]
        return [int(d.strip()) for d in self.work_days.split(",") if d.strip()]


class ContractAttributeDefinition(models.Model):
    """Définit un champ personnalisé additionnel pour les contrats,
    ajoutable depuis l'admin Django SANS toucher au code (ex : « Véhicule de
    fonction », « Numéro de badge »...). Apparaît automatiquement sur le
    formulaire de contrat (création ET modification), et sur la fiche
    « Voir » du contrat."""

    class FieldType(models.TextChoices):
        TEXT = "TEXT", "Texte court"
        NUMBER = "NUMBER", "Nombre"
        DATE = "DATE", "Date"
        BOOLEAN = "BOOLEAN", "Oui / Non"
        CHOICE = "CHOICE", "Liste de choix"

    name = models.SlugField(
        "Nom du champ (interne)", max_length=50, unique=True,
        help_text="Identifiant technique, sans espace ni accent (ex : vehicule_fonction).",
    )
    label = models.CharField("Libellé affiché", max_length=100)
    field_type = models.CharField(
        "Type de champ", max_length=10, choices=FieldType.choices, default=FieldType.TEXT
    )
    choices = models.CharField(
        "Options (si liste de choix)", max_length=500, blank=True,
        help_text="Uniquement pour le type « Liste de choix » — séparées par des virgules. Ex : Oui,Non,En attente",
    )
    required = models.BooleanField("Obligatoire", default=False)
    order = models.PositiveIntegerField("Ordre d'affichage", default=0)
    active = models.BooleanField(
        "Actif", default=True,
        help_text="Décocher pour retirer ce champ du formulaire sans supprimer les valeurs déjà saisies.",
    )

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "Attribut de contrat personnalisé"
        verbose_name_plural = "Attributs de contrat personnalisés"

    def __str__(self):
        return self.label

    def choices_list(self):
        return [c.strip() for c in self.choices.split(",") if c.strip()]


class ContractAttributeValue(models.Model):
    """Valeur d'un attribut personnalisé pour un contrat donné.

    on_delete=PROTECT (volontairement, PAS CASCADE) : si l'admin supprime un
    ContractAttributeDefinition qui a déjà des valeurs enregistrées sur des
    contrats existants, Django REFUSE la suppression plutôt que d'effacer
    silencieusement les données de ces anciens contrats. Pour retirer un
    champ du formulaire sans toucher à l'historique, il faut décocher
    « Actif » sur le champ — jamais le supprimer."""
    contract = models.ForeignKey(Contract, on_delete=models.CASCADE, related_name="attribute_values")
    definition = models.ForeignKey(ContractAttributeDefinition, on_delete=models.PROTECT, related_name="values")
    value = models.CharField("Valeur", max_length=500, blank=True)

    class Meta:
        unique_together = ("contract", "definition")
        verbose_name = "Valeur d'attribut de contrat"
        verbose_name_plural = "Valeurs d'attributs de contrat"

    def __str__(self):
        return f"{self.definition.label} = {self.value}"

    def display_value(self):
        if self.definition.field_type == ContractAttributeDefinition.FieldType.BOOLEAN:
            return "Oui" if self.value == "True" else "Non"
        return self.value