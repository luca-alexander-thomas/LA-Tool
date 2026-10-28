from django import forms
from django.contrib.auth.models import Group
from django.core.validators import FileExtensionValidator
from app.models import Questions_Catalogs, Questions_Theory, Questions_Practical, Questions_GroupExercise, Exams, Work, Levels

_PDF_IMAGE_VALIDATOR = FileExtensionValidator(allowed_extensions=['pdf', 'png', 'jpg', 'jpeg'])


class LevelForm(forms.ModelForm):
    class Meta:
        model = Levels
        fields = [
            'name', 'slug', 'order', 'icon',
            'badge_bg_class', 'badge_text_class',
            'default_training_count', 'default_training_pass_pct',
            'default_exam_count', 'default_exam_pass_pct',
            'is_draft',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'z.B. LA-Bronze'}),
            'slug': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'z.B. bronze'}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'icon': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'badge_bg_class': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'z.B. bg-warning'}),
            'badge_text_class': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'z.B. text-dark'}),
            'default_training_count': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'default_training_pass_pct': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 100}),
            'default_exam_count': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'default_exam_pass_pct': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 100}),
            'is_draft': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'name': 'Name',
            'slug': 'Slug (URL-Bezeichner)',
            'order': 'Reihenfolge',
            'icon': 'Logo / Symbol',
            'badge_bg_class': 'Hintergrundfarbe (CSS-Klasse)',
            'badge_text_class': 'Textfarbe (CSS-Klasse)',
            'default_training_count': 'Standard Trainingsanzahl (Fragen)',
            'default_training_pass_pct': 'Standard Bestehensgrenze Training (%)',
            'default_exam_count': 'Standard Prüfungsanzahl (Fragen)',
            'default_exam_pass_pct': 'Standard Bestehensgrenze Prüfung (%)',
            'is_draft': 'Entwurf (für User unsichtbar)',
        }


class CatalogForm(forms.ModelForm):
    class Meta:
        model = Questions_Catalogs
        fields = ['title', 'short_title', 'level', 'multi_answer_scoring', 'icon', 'is_draft']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Katalog-Name'}),
            'short_title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Kurztitel (max. 20 Zeichen)'}),
            'level': forms.Select(attrs={'class': 'form-select'}),
            'multi_answer_scoring': forms.Select(attrs={'class': 'form-select'}),
            'icon': forms.FileInput(attrs={'class': 'form-control'}),
            'is_draft': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'title': 'Name',
            'short_title': 'Kurztitel',
            'level': 'LA-Stufe',
            'multi_answer_scoring': 'Bewertung Mehrfachantworten',
            'icon': 'Icon',
            'is_draft': 'Entwurf (für User unsichtbar)',
        }


class TheoryQuestionForm(forms.Form):
    """Handles only the static fields; choices + correct are processed from raw POST."""
    number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'z.B. S-1-01'}),
        label='Nummer',
    )
    question = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Fragetext'}),
        label='Frage',
    )
    help_reference = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Hinweise / Hilfe (optional)'}),
        label='Hinweise',
    )

    @staticmethod
    def parse_choices_from_post(post):
        """Returns (choices: list[str], correct_texts: list[str])."""
        choices = [c.strip() for c in post.getlist('choice') if c.strip()]
        correct_indices = post.getlist('correct')
        correct_texts = []
        for idx_str in correct_indices:
            try:
                idx = int(idx_str)
                if 0 <= idx < len(choices):
                    correct_texts.append(choices[idx])
            except (ValueError, TypeError):
                pass
        return choices, correct_texts

    def save_to_model(self, catalog, choices, correct_texts, instance=None):
        if not correct_texts:
            raise ValueError('Mindestens eine richtige Antwort muss angegeben werden.')
        data = self.cleaned_data
        if instance is None:
            instance = Questions_Theory()
        instance.catalog = catalog
        instance.number = data.get('number', '')
        instance.question = data['question']
        instance.answer_choice = choices
        instance.answer_correct = correct_texts
        instance.answer_text = correct_texts[0] if correct_texts else ''
        instance.help_reference = data.get('help_reference', '')
        instance.save()
        return instance


class ImportQuestionForm(forms.Form):
    catalog = forms.ModelChoiceField(
        queryset=Questions_Catalogs.objects.select_related('level').all().order_by('level__order', 'title'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Ziel-Katalog',
        empty_label='— Katalog wählen —',
    )
    file = forms.FileField(
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.csv,.json,.xlsx'}),
        label='Datei (XLSX, CSV oder JSON)',
    )
    update_existing = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Bestehende Fragen (gleiche Nummer) aktualisieren',
    )


class PracticalForm(forms.ModelForm):
    # Explicit class-level declaration ensures FileInput is always used,
    # preventing Django's ModelForm metaclass from substituting ClearableFileInput.
    file = forms.FileField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf,.png,.jpg,.jpeg'}),
        label='PDF / Bild',
        validators=[_PDF_IMAGE_VALIDATOR],
    )

    class Meta:
        model = Questions_Practical
        fields = ['number', 'question', 'file', 'help_reference']
        widgets = {
            'number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'z.B. P1'}),
            'question': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Aufgabentitel'}),
            'help_reference': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Hinweise (optional)'}),
        }
        labels = {
            'number': 'Nummer',
            'question': 'Aufgabe',
            'help_reference': 'Hinweise',
        }


class GroupExerciseForm(forms.ModelForm):
    # Explicit class-level declaration ensures FileInput is always used,
    # preventing Django's ModelForm metaclass from substituting ClearableFileInput.
    file = forms.FileField(
        required=False,
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.pdf,.png,.jpg,.jpeg'}),
        label='PDF / Bild',
        validators=[_PDF_IMAGE_VALIDATOR],
    )

    class Meta:
        model = Questions_GroupExercise
        fields = ['number', 'question', 'file', 'help_reference']
        widgets = {
            'number': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'z.B. G1'}),
            'question': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Aufgabentitel'}),
            'help_reference': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Hinweise (optional)'}),
        }
        labels = {
            'number': 'Nummer',
            'question': 'Aufgabe',
            'help_reference': 'Hinweise',
        }


class WorkForm(forms.ModelForm):
    class Meta:
        model = Work
        fields = ['level', 'description', 'is_draft']
        widgets = {
            'level': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Hinweise, Agenda, Beschreibung...'}),
            'is_draft': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'level': 'LA-Stufe',
            'description': 'Beschreibung / Agenda',
            'is_draft': 'Entwurf (für User unsichtbar)',
        }


class WorkCreateForm(forms.ModelForm):
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.order_by('name'),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
        label='Gruppen (leer = alle sehen den Dienst)',
    )

    class Meta:
        model = Work
        fields = ['title', 'date', 'date_end', 'location', 'level', 'description', 'groups', 'is_draft']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Dienstbezeichnung'}),
            'date': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'date_end': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ort (optional)'}),
            'level': forms.Select(attrs={'class': 'form-select'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Beschreibung / Agenda...'}),
            'is_draft': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'title': 'Bezeichnung',
            'date': 'Beginn',
            'date_end': 'Ende (optional)',
            'location': 'Ort',
            'level': 'LA-Stufe',
            'description': 'Beschreibung / Agenda',
            'is_draft': 'Entwurf (für User unsichtbar)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['date'].input_formats = ['%Y-%m-%dT%H:%M']
        self.fields['date_end'].input_formats = ['%Y-%m-%dT%H:%M']


class AutoGroupRuleForm(forms.Form):
    group_name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'z.B. LA-Bronze Teilnehmer'}),
        label='Gruppenname',
    )
    entra_group_ids_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control', 'rows': 3,
            'placeholder': 'Eine Entra-Gruppen-ID pro Zeile\nz.B. xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx',
        }),
        label='Entra-Gruppen-IDs (eine pro Zeile)',
    )


class ExamForm(forms.ModelForm):
    class Meta:
        model = Exams
        fields = ['name', 'level', 'time_in_min', 'pass_threshold', 'info_text', 'end_text', 'visible', 'closed', 'archived']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Prüfungstitel'}),
            'level': forms.Select(attrs={'class': 'form-select'}),
            'time_in_min': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Zeit in Minuten', 'min': 1}),
            'pass_threshold': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'info_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Infotext für die Prüfungseinleitung (optional)'}),
            'end_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Abschlussnachricht (optional)'}),
            'visible': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'closed': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'archived': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'name': 'Prüfungstitel',
            'level': 'LA-Stufe',
            'time_in_min': 'Zeit in Minuten',
            'pass_threshold': 'Bestehensgrenze (Punkte)',
            'info_text': 'Infotext',
            'end_text': 'Abschlussnachricht',
            'visible': 'Sichtbar für Nutzer',
            'closed': 'Gesperrt (keine Abgaben möglich)',
            'archived': 'Archiviert',
        }
