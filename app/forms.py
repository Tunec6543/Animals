import logging
import re
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
    _phone_chars(value)
    digits = sum(ch.isdigit() for ch in value)
    if not 10 <= digits <= 15:
        raise forms.ValidationError(PHONE_MESSAGE)


def name_validator(value):
    if not all(ch.isalpha() or ch in ' -' for ch in value):
        raise forms.ValidationError('ФИО может содержать только буквы, пробел и дефис')


EMAIL_INVALID = 'Проверьте e-mail, например name@example.ru'


class NameCleanMixin:
    def clean_last_name(self):
        name_validator(self.cleaned_data['last_name'])
        return self.cleaned_data['last_name']

    def clean_first_name(self):
        name_validator(self.cleaned_data['first_name'])
        return self.cleaned_data['first_name']


class StyledFormMixin:
    messages = {}
    placeholders = {}

    def _style_fields(self):
        for name, field in self.fields.items():
            field.error_messages.update(self.messages.get(name, {}))
            css = 'field__input'
            if isinstance(field.widget, forms.Textarea):
                css += ' field__input--area'
            field.widget.attrs['class'] = css
            if name in self.placeholders:
                field.widget.attrs['placeholder'] = self.placeholders[name]
            for code, attr in (('required', 'msg-required'), ('invalid', 'msg-invalid'),
                               ('min_value', 'msg-min'), ('max_value', 'msg-max')):
                if code in field.error_messages and (code != 'required' or field.required):
                    field.widget.attrs['data-' + attr] = str(field.error_messages[code])


LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 15 * 60


class LoginForm(StyledFormMixin, AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': 'Неверный логин или пароль. Проверьте данные и попробуйте снова',
    }
    messages = {
        'username': {'required': 'Введите логин'},
        'password': {'required': 'Введите пароль'},
    }
    placeholders = {'username': 'Логин', 'password': 'Пароль'}

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

class RegisterForm(NameCleanMixin, StyledFormMixin, forms.ModelForm):
    messages = {
        'last_name': {'required': 'Введите фамилию'},
        'first_name': {'required': 'Введите имя'},
        'username': {
            'required': 'Введите логин',
            'unique': 'Этот логин уже занят. Попробуйте другой',
        },
        'email': {'required': 'Введите e-mail', 'invalid': EMAIL_INVALID},
        'phone': {'required': 'Введите телефон'},
        'password': {
            'required': 'Введите пароль',
            'min_length': 'Пароль слишком короткий: нужно не менее 8 символов',
        },
        'password2': {'required': 'Повторите пароль'},
    }
    placeholders = {
        'last_name': 'Иванов', 'first_name': 'Иван', 'username': 'Придумайте логин',
        'email': 'name@example.ru', 'phone': '+7 900 000-00-00',
        'password': 'Не менее 8 символов', 'password2': 'Повторите пароль',
    }
    password = forms.CharField(label='Пароль', min_length=8, widget=forms.PasswordInput)
    password2 = forms.CharField(label='Подтверждение пароля', widget=forms.PasswordInput)
    phone = forms.CharField(
        label='Телефон', validators=[phone_validator],
        widget=forms.TextInput(attrs={'type': 'tel', 'data-msg-invalid': PHONE_MESSAGE}),
    )

    class Meta:
        model = User
        fields = ('last_name', 'first_name', 'username', 'email')
        labels = {
            'last_name': 'Фамилия', 'first_name': 'Имя',
            'username': 'Логин', 'email': 'E-mail',
        }
        error_messages = {'username': {'unique': 'Этот логин уже занят. Попробуйте другой'}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('last_name', 'first_name', 'email'):
            self.fields[name].required = True
        self._style_fields()

    def clean_username(self):
        username = self.cleaned_data['username']
        if not re.fullmatch(r'\w{3,30}', username):
            raise forms.ValidationError('Логин: от 3 до 30 символов — буквы, цифры и знак «_»')
        return username

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Этот e-mail уже зарегистрирован. Войдите в аккаунт')
        return email

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password')
        password2 = cleaned.get('password2')

        if password and password2 and password != password2:
            self.add_error('password2', 'Пароли не совпадают. Введите один и тот же пароль дважды.')

        if password and password.isdigit():
            self.add_error('password', 'Добавьте в пароль буквы')
        elif password:
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
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.phone = self.cleaned_data['phone']
            profile.save()
        return user


class AdoptionForm(StyledFormMixin, forms.ModelForm):
    messages = {
        'housing_conditions': {
            'required': 'Опишите жилищные условия',
            'min_length': 'Опишите подробнее: не менее 20 символов (сейчас: %(show_value)d)',
        },
        'experience': {
            'required': 'Опишите опыт содержания животных',
            'min_length': 'Опишите подробнее: не менее 20 символов (сейчас: %(show_value)d)',
        },
    }
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
    messages = {'date_time': {
        'required': 'Выберите дату и время прогулки',
        'invalid': 'Введите дату и время в формате ДД.ММ.ГГГГ ЧЧ:ММ',
    }}
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
    messages = {
        'name': {'required': 'Введите имя', 'min_length': 'Имя слишком короткое: не менее 2 символов'},
        'email': {'required': 'Введите e-mail', 'invalid': EMAIL_INVALID},
        'message': {
            'required': 'Введите сообщение',
            'min_length': 'Сообщение слишком короткое: не менее 10 символов (сейчас: %(show_value)d)',
            'max_length': 'Сообщение слишком длинное: не более 1000 символов (сейчас: %(show_value)d)',
        },
    }
    name = forms.CharField(label='Имя', min_length=2, max_length=100)
    email = forms.EmailField(label='Email')
    phone = forms.CharField(label='Телефон', required=False, validators=[phone_validator],
                            widget=forms.TextInput(attrs={'type': 'tel', 'data-msg-invalid': PHONE_MESSAGE}))
    message = forms.CharField(label='Сообщение', min_length=10, max_length=1000,
                              widget=forms.Textarea(attrs={'rows': 5}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._style_fields()


class DonateForm(StyledFormMixin, forms.ModelForm):
    messages = {
        'pet': {'required': 'Выберите питомца из списка', 'invalid_choice': 'Выберите питомца из списка'},
        'amount': {
            'required': 'Введите сумму пожертвования',
            'invalid': 'Введите сумму цифрами, например 500',
            'min_value': 'Минимальная сумма — 50 ₽',
            'max_value': 'Максимальная сумма — 100 000 ₽',
        },
        'payment_type': {
            'required': 'Выберите способ оплаты из списка',
            'invalid_choice': 'Выберите способ оплаты из списка',
        },
        'comment': {'max_length': 'Комментарий слишком длинный: не более 500 символов (сейчас: %(show_value)d)'},
    }
    pet = forms.ModelChoiceField(
        label='Питомец', queryset=Pet.objects.exclude(status='adopted'), empty_label='Выберите питомца',
    )
    amount = forms.IntegerField(
        label='Сумма взноса, ₽', min_value=50, max_value=100000,
        widget=forms.NumberInput(attrs={'min': 50, 'max': 100000, 'step': 1, 'placeholder': 'Например, 500 ₽'}),
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


class ProfileForm(NameCleanMixin, StyledFormMixin, forms.ModelForm):
    messages = {'email': {'required': 'Введите e-mail', 'invalid': EMAIL_INVALID}}
    email = forms.EmailField(label='E-mail')
    phone = forms.CharField(label='Телефон', required=False, validators=[phone_validator],
                            widget=forms.TextInput(attrs={'type': 'tel', 'data-msg-invalid': PHONE_MESSAGE}))
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
        email = self.cleaned_data['email']
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Этот e-mail уже зарегистрирован. Войдите в аккаунт')
        return email

    def save(self, commit=True):
        user = super().save(commit)
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.phone = self.cleaned_data['phone']
        profile.gender = self.cleaned_data['gender']
        profile.save()
        return user
