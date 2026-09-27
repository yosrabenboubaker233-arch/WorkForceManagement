from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Utilisateur Workforce Management étendu avec un rôle métier."""

    class Role(models.TextChoices):
        EMPLOYEE = "EMPLOYEE", "Employé"
        MANAGER = "MANAGER", "Manager / Chef"
        RH = "RH", "Ressources Humaines"
        PAYROLL = "PAYROLL", "Back-office Paie"
        DIRECTION = "DIRECTION", "Direction Générale"
        ADMIN = "ADMIN", "Super Administrateur"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.EMPLOYEE)
    phone = models.CharField(max_length=30, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)

    def is_manager(self):
        return self.role == self.Role.MANAGER

    def is_rh(self):
        return self.role in (self.Role.RH, self.Role.ADMIN)

    def is_payroll(self):
        return self.role in (self.Role.PAYROLL, self.Role.ADMIN)

    def is_direction(self):
        return self.role in (self.Role.DIRECTION, self.Role.ADMIN)

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.get_role_display()})"
