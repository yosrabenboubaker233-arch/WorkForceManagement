# TeamDev HR — Plateforme de gestion des ressources humaines

Application Django complète : gestion des employés, congés, pointage/absences
et back-office paie, avec le thème visuel TeamDev (dégradé bleu → turquoise →
violet sur fond bleu nuit).

## 1. Installation

```bash
python -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Base de données

```bash
python manage.py makemigrations
python manage.py migrate
```

## 3. Jeu de données de démonstration (optionnel mais recommandé)

```bash
python manage.py seed_demo
```

Comptes créés :

| Rôle          | Utilisateur | Mot de passe |
|---------------|-------------|--------------|
| Super Admin   | admin       | admin123     |
| Manager       | manager1    | manager123   |
| Employé       | employe1    | employe123   |
| RH            | rh1         | rh123456     |
| Back-office Paie | paie1    | paie12345    |

## 4. Lancement

```bash
python manage.py runserver
```

Application disponible sur http://127.0.0.1:8000/
Interface d'administration Django : http://127.0.0.1:8000/admin/

## 5. Détection automatique des absences (règle métier clé)

Une commande dédiée vérifie, pour une date donnée, quels employés n'ont pas
pointé, met à jour leur statut (Absent / En congé) et envoie **automatiquement
une notification au manager** si l'absence coïncide avec un congé refusé :

```bash
python manage.py detect_absences
# ou pour une date précise :
python manage.py detect_absences --date 2026-07-02
```

En production, planifiez cette commande chaque jour via cron (ou Celery beat) :

```
0 10 * * 1-5 /chemin/vers/venv/bin/python /chemin/vers/manage.py detect_absences
```

## 6. Structure du projet

```
teamdev_hr/
├── accounts/       # Utilisateur personnalisé + rôles (Employé, Manager, RH, Paie, Admin)
├── employees/      # Dossier employé : CV, historique, temps de travail, organigramme
├── leaves/         # Demandes de congé, validation hiérarchique, notifications
├── attendance/     # Pointage, détection d'absence, alertes automatiques
├── payroll/        # Salaires, augmentations, historique de rémunération
├── notifications/  # Notifications transverses à tous les modules
├── templates/       # Templates globaux (base, dashboards par rôle)
└── static/css/style.css  # Thème visuel TeamDev
```

## 7. Rôles & permissions

- **Employé** : dossier personnel (lecture), CV/documents, demande de congé, pointage.
- **Manager** : dossiers de son équipe, validation des congés de son équipe, alertes d'absence.
- **RH / Admin** : gestion complète des employés, historique global des congés, organigramme.
- **Back-office Paie** : gestion des salaires et des augmentations (accès restreint).

## 8. Aller plus loin

- Ajouter l'authentification à deux facteurs (django-otp).
- Ajouter des exports PDF/Excel (reportlab / openpyxl).
- Ajouter Celery + Celery Beat pour automatiser `detect_absences` sans cron système.
- Ajouter des tests unitaires (pytest-django).
