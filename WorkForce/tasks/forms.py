from django import forms
from .models import Task, TaskComment
from employees.models import Employee


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ["employee", "title", "description", "due_date"]
        widgets = {
            "employee": forms.Select(attrs={"class": "td-input"}),
            "title": forms.TextInput(attrs={"class": "td-input", "placeholder": "Ex : préparer la démo client"}),
            "description": forms.Textarea(attrs={"class": "td-input", "rows": 4}),
            "due_date": forms.DateInput(attrs={"type": "date", "class": "td-input"}),
        }

    def __init__(self, *args, manager=None, **kwargs):
        super().__init__(*args, **kwargs)
        if manager is not None:
            self.fields["employee"].queryset = Employee.objects.filter(manager=manager)


class TaskStatusForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = ["status"]
        widgets = {"status": forms.Select(attrs={"class": "td-input"})}

class TaskCommentForm(forms.ModelForm):
    class Meta:
        model = TaskComment
        fields = ["message", "report"]
        widgets = {
            "message": forms.Textarea(attrs={"class": "td-input", "rows": 2, "placeholder": "Écrire un message..."}),
            "report": forms.ClearableFileInput(attrs={"class": "td-input"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        message = (cleaned_data.get("message") or "").strip()
        report = cleaned_data.get("report")
        if not message and not report:
            raise forms.ValidationError("Écrivez un message ou joignez un rapport.")
        return cleaned_data