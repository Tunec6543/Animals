import logging
from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache
from django.contrib.auth.password_validation import validate_password
from django.core.validators import RegexValidator
from django.utils import timezone

from .models import AdoptionApplication, Pet, Profile, SponsorshipPayment, WalkingBooking

User = get_user_model()

logger = logging.getLogger(__name__)

PHONE_MESSAGE = 'Введите телефон в формате +7 900 000-00-00.'
_phone_chars = RegexValidator(r'^\+?[\d\s()-]{10,18}$', PHONE_MESSAGE)


def phone_validator(value):
    # BUG-11: помимо допустимых символов в номере должно быть от 10 до 15 цифр
    _phone_chars(value)
    digits = sum(ch.isdigit() for ch in value)
    if not 10 <= digits <= 15:
        raise forms.ValidationError(PHONE_MESSAGE)


class StyledFormMixin:
    def _style_fields(self):
        for field in self.fields.values():
            css = 'field__input'
            if isinstance(field.widget, forms.Textarea):
                css += ' field__input--area'
            field.widget.attrs['class'] = css


LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 15 * 60


class LoginForm(StyledFormMixin, AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = 'Логин'
        self._style_fields()

    def _fail_key(self, username):
        ip = self.request.META.get('REMOTE_ADDR', '') if self.request else ''
        return f'login-fail:{ip}:{(username or "").lower()}'

    def clean(self):
        username = self.cleaned_data.get('username')
        key = self._fail_key(username)

        if cache.get(key, 0) >= LOGIN_MAX_ATTEMPTS:
            logger.warning(
                'Вход заблокирован после серии неудачных попыток: логин=%s',
                username
            )
            raise forms.ValidationError(
                'Слишком много неудачных попыток входа. Повторите через 15 минут.',
                code='locked'
            )

        try:
            result = super().clean()
        except forms.ValidationError:
            logger.warning(
                'Неудачная попытка входа: логин=%s',
                username
            )
            cache.add(key, 0, LOGIN_LOCK_SECONDS)

            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, LOGIN_LOCK_SECONDS)

            raise

        cache.delete(key)
        return result

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

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password')

        if password:
            candidate = User(
                username=cleaned.get('username', ''),
                email=cleaned.get('email', '')
            )

            try:
                validate_password(password, candidate)
            except forms.ValidationError as error:
                self.add_error('password', error)

        return cleaned

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
        now = now = timezone.now()
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
    amount = forms.IntegerField(
        label='Сумма взноса, ₽', min_value=50, max_value=100000,
        error_messages={'invalid': 'Введите целое число рублей, например 500.'},
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

    def clean_email(self):
        # BUG-04: email должен оставаться уникальным (как при регистрации), свой текущий email допустим
        email = self.cleaned_data['email']
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Пользователь с таким email уже зарегистрирован.')
        return email

    def save(self, commit=True):
        user = super().save(commit)
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.phone = self.cleaned_data['phone']
        profile.gender = self.cleaned_data['gender']
        profile.save()
        return user
