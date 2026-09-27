from django.contrib import admin
from .models import Task, TaskComment


class TaskCommentInline(admin.TabularInline):
    model = TaskComment
    extra = 0


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "employee", "assigned_by", "status", "due_date")
    list_filter = ("status",)
    search_fields = ("title", "employee__user__first_name", "employee__user__last_name")
    inlines = [TaskCommentInline]
