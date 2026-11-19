from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.validators import RegexValidator
from django.utils import timezone

from .models import AdoptionApplication, Pet, Profile, SponsorshipPayment, WalkingBooking

User = get_user_model()

phone_validator = RegexValidator(
    r'^\+?[\d\s()-]{10,18}$', 'Введите телефон в формате +7 900 000-00-00.'
)


class StyledFormMixin:
    def _style_fields(self):
        for field in self.fields.values():
            css = 'field__input'
            if isinstance(field.widget, forms.Textarea):
                css += ' field__input--area'
            field.widget.attrs['class'] = css


class LoginForm(StyledFormMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = 'Логин'
        self._style_fields()


class RegisterForm(StyledFormMixin, forms.ModelForm):
    password = forms.CharField(label='Пароль', min_length=8, widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ('username', 'email')
        labels = {'username': 'Логин', 'email': 'Email'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['email'].required = True
        self._style_fields()

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Пользователь с таким email уже зарегистрирован.')
        return email

    def clean_password(self):
        password = self.cleaned_data['password']
        validate_password(password)
        return password

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user


class AdoptionForm(StyledFormMixin, forms.ModelForm):
    housing_conditions = forms.CharField(
        label='Жилищные условия', min_length=20, max_length=1000,
        widget=forms.Textarea(attrs={'rows': 4}),
    )
    experience = forms.CharField(
        label='Опыт содержания животных', min_length=20, max_length=1000,
        widget=forms.Textarea(attrs={'rows': 4}),
    )

    class Meta:
        model = AdoptionApplication
        fields = ('housing_conditions', 'experience')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class WalkForm(StyledFormMixin, forms.ModelForm):
    date_time = forms.DateTimeField(
        label='Дата и время прогулки',
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
    )

    class Meta:
        model = WalkingBooking
        fields = ('date_time',)

    def __init__(self, *args, pet=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.pet = pet
        self._style_fields()

    def clean_date_time(self):
        value = self.cleaned_data['date_time']
        now = timezone.now()
        local = timezone.localtime(value)
        if value <= now:
            raise forms.ValidationError('Выберите время в будущем.')
        if value > now + timedelta(days=30):
            raise forms.ValidationError('Записаться можно не более чем на 30 дней вперёд.')
        if not 9 <= local.hour < 18:
            raise forms.ValidationError('Прогулки проходят с 9:00 до 18:00.')
        if WalkingBooking.objects.filter(pet=self.pet, date_time=value).exists():
            raise forms.ValidationError('На это время питомец уже записан на прогулку.')
        return value


class ContactForm(StyledFormMixin, forms.Form):
    name = forms.CharField(label='Имя', min_length=2, max_length=100)
    email = forms.EmailField(label='Email')
    phone = forms.CharField(label='Телефон', required=False, validators=[phone_validator],
                            widget=forms.TextInput(attrs={'type': 'tel'}))
    message = forms.CharField(label='Сообщение', min_length=10, max_length=1000,
                              widget=forms.Textarea(attrs={'rows': 5}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class DonateForm(StyledFormMixin, forms.ModelForm):
    pet = forms.ModelChoiceField(
        label='Питомец', queryset=Pet.objects.exclude(status='adopted'), empty_label='Выберите питомца',
    )
    amount = forms.DecimalField(
        label='Сумма взноса, ₽', min_value=50, max_value=100000, max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={'min': 50, 'max': 100000, 'step': 1, 'placeholder': 'Сумма ₽...'}),
    )
    payment_type = forms.ChoiceField(
        label='Тип оплаты', choices=[('', 'Выберите тип оплаты')] + SponsorshipPayment.PAYMENT_CHOICES,
    )
    comment = forms.CharField(
        label='Комментарий', required=False, max_length=500,
        widget=forms.Textarea(attrs={'rows': 8, 'placeholder': 'Комментарий (необязательно)...'}),
    )

    class Meta:
        model = SponsorshipPayment
        fields = ('pet', 'amount', 'payment_type', 'comment')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()
        for name in ('pet', 'payment_type'):
            self.fields[name].widget.attrs['class'] += ' field__input--select'


class ProfileForm(StyledFormMixin, forms.ModelForm):
    email = forms.EmailField(label='Email')
    phone = forms.CharField(label='Телефон', required=False, validators=[phone_validator],
                            widget=forms.TextInput(attrs={'type': 'tel'}))
    gender = forms.ChoiceField(label='Пол', required=False, choices=[('', 'Не указан')] + Profile.GENDER_CHOICES)

    class Meta:
        model = User
        fields = ('last_name', 'first_name', 'email')
        labels = {'last_name': 'Фамилия', 'first_name': 'Имя'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        profile, _ = Profile.objects.get_or_create(user=self.instance)
        self.fields['phone'].initial = profile.phone
        self.fields['gender'].initial = profile.gender
        self._style_fields()

    def save(self, commit=True):
        user = super().save(commit)
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.phone = self.cleaned_data['phone']
        profile.gender = self.cleaned_data['gender']
        profile.save()
        return user
