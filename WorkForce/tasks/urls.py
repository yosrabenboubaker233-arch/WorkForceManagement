from django.urls import path
from . import views

app_name = "tasks"

urlpatterns = [
    path("", views.my_tasks, name="my_tasks"),
    path("equipe/", views.team_tasks, name="team_tasks"),
    path("nouvelle/", views.task_create, name="create"),
    path("<int:pk>/modifier/", views.task_edit, name="edit"),
    path("<int:pk>/supprimer/", views.task_delete, name="delete"),
    path("<int:pk>/", views.task_detail, name="detail"),
]