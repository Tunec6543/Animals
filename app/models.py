from django.conf import settings
from django.db import models
from django.db.models import Q
from .validators import validate_image_file

class Volier(models.Model):
    number = models.CharField('Номер/название вольера', max_length=50, unique=True)
    sector = models.CharField('Сектор приюта', max_length=100)
    capacity = models.PositiveIntegerField('Вместимость', default=1)

    def __str__(self):
        return f'Вольер №{self.number} ({self.sector})'

    class Meta:
        verbose_name = 'Вольер'
        verbose_name_plural = 'Вольеры'
        ordering = ['sector', 'number']
        constraints = [
            models.CheckConstraint(condition=Q(capacity__gte=1), name='volier_capacity_gte_1'),
        ]


class Pet(models.Model):
    STATUS_CHOICES = [
        ('available', 'Доступен'),
        ('quarantine', 'На карантине'),
        ('treatment', 'На лечении'),
        ('reserved', 'Забронирован'),
        ('adopted', 'Обрёл дом'),
    ]
    GENDER_CHOICES = [('male', 'Мальчик'), ('female', 'Девочка')]
    SPECIES_CHOICES = [('dog', 'Собака'), ('cat', 'Кошка'), ('other', 'Другое')]

    name = models.CharField('Кличка', max_length=100)
    species = models.CharField('Вид', max_length=20, choices=SPECIES_CHOICES)
    breed = models.CharField('Порода', max_length=100, blank=True)
    age = models.PositiveSmallIntegerField('Возраст (полных лет)')
    gender = models.CharField('Пол', max_length=10, choices=GENDER_CHOICES)
    status = models.CharField('Статус', max_length=20, choices=STATUS_CHOICES, default='available')
    description = models.TextField('История и характер', blank=True)
    photo = models.ImageField(
        'Фотография',
        upload_to='pets/',
        blank=True,
        validators=[validate_image_file]
    )
    volier = models.ForeignKey(
        Volier, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pets', verbose_name='Вольер',
    )
    admission_date = models.DateField('Дата поступления', auto_now_add=True)
    sponsors = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through='SponsorshipPayment',
        related_name='sponsored_pets', verbose_name='Опекуны',
    )

    def __str__(self):
        return f'{self.name} ({self.get_species_display()}, {self.get_status_display()})'

    class Meta:
        verbose_name = 'Питомец'
        verbose_name_plural = 'Питомцы'
        ordering = ['-admission_date', 'name']
        constraints = [
            models.CheckConstraint(condition=Q(age__gte=0) & Q(age__lte=40), name='pet_age_0_40'),
        ]


class VetCard(models.Model):
    pet = models.OneToOneField(
        Pet, on_delete=models.CASCADE, related_name='vet_card', verbose_name='Питомец'
    )
    last_checkup = models.DateField('Дата последнего осмотра')
    vaccinations = models.TextField('Прививки и обработки')
    diagnosis = models.TextField('Текущий диагноз / Особенности', blank=True)

    def __str__(self):
        return f'Веткарточка: {self.pet.name}'

    class Meta:
        verbose_name = 'Ветеринарная карточка'
        verbose_name_plural = 'Ветеринарные карточки'
        ordering = ['-last_checkup']


class AdoptionApplication(models.Model):
    STATUS_CHOICES = [
        ('pending', 'На рассмотрении'),
        ('approved', 'Одобрена (ожидает договора)'),
        ('rejected', 'Отклонена'),
        ('completed', 'Договор подписан (обрёл дом)'),
    ]
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='adoption_applications', verbose_name='Кандидат'
    )
    pet = models.ForeignKey(
        Pet, on_delete=models.CASCADE, related_name='applications', verbose_name='Питомец'
    )
    housing_conditions = models.TextField('Жилищные условия')
    experience = models.TextField('Опыт содержания животных')
    status = models.CharField('Статус заявки', max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField('Дата подачи', auto_now_add=True)

    def __str__(self):
        return f'Заявка #{self.pk} от {self.user.username} на {self.pet.name}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # BUG-01: одобренная заявка бронирует питомца, чтобы на него нельзя было подать новую заявку
        if self.status == 'approved':
            Pet.objects.filter(pk=self.pet_id, status='available').update(status='reserved')

    class Meta:
        verbose_name = 'Анкета на усыновление'
        verbose_name_plural = 'Анкеты на усыновление'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'pet'], name='unique_user_pet_application'),
        ]


class Interview(models.Model):
    application = models.OneToOneField(
        AdoptionApplication, on_delete=models.CASCADE,
        related_name='interview', verbose_name='Анкета',
    )
    curator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='curator_interviews', verbose_name='Куратор',
    )
    scheduled_time = models.DateTimeField('Дата и время собеседования')
    passed = models.BooleanField('Собеседование пройдено успешно', default=False)
    notes = models.TextField('Заметки куратора', blank=True)

    def __str__(self):
        return f'Собеседование по заявке #{self.application_id}'

    class Meta:
        verbose_name = 'Собеседование'
        verbose_name_plural = 'Собеседования'
        ordering = ['scheduled_time']


class WalkingBooking(models.Model):
    volunteer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='walking_bookings', verbose_name='Волонтёр'
    )
    pet = models.ForeignKey(
        Pet, on_delete=models.CASCADE, related_name='walks', verbose_name='Питомец'
    )
    date_time = models.DateTimeField('Дата и время прогулки')
    is_completed = models.BooleanField('Прогулка завершена', default=False)

    def __str__(self):
        return f'Прогулка с {self.pet.name} ({self.date_time:%d.%m.%Y %H:%M})'

    class Meta:
        verbose_name = 'Запись на прогулку'
        verbose_name_plural = 'Записи на прогулки'
        ordering = ['-date_time']


class AdoptionContract(models.Model):
    application = models.OneToOneField(
        AdoptionApplication, on_delete=models.CASCADE,
        related_name='contract', verbose_name='Анкета / Заявка',
    )
    signed_date = models.DateField('Дата подписания', auto_now_add=True)
    terms_agreed = models.BooleanField('Условия содержания приняты', default=True)

    def __str__(self):
        return f'Договор #{self.pk} по питомцу {self.application.pet.name}'

    class Meta:
        verbose_name = 'Договор передачи'
        verbose_name_plural = 'Договоры передачи'
        ordering = ['-signed_date']


class SponsorshipPayment(models.Model):
    PAYMENT_CHOICES = [
        ('card', 'Банковская карта'),
        ('sbp', 'Система быстрых платежей'),
        ('cash', 'Наличными в приюте'),
    ]
    sponsor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='sponsorship_payments', verbose_name='Опекун'
    )
    pet = models.ForeignKey(
        Pet, on_delete=models.CASCADE, related_name='sponsorships', verbose_name='Питомец'
    )
    amount = models.DecimalField('Сумма взноса (руб.)', max_digits=10, decimal_places=2)
    payment_type = models.CharField('Тип оплаты', max_length=10, choices=PAYMENT_CHOICES, default='card')
    comment = models.TextField('Комментарий', blank=True)
    payment_date = models.DateTimeField(auto_now_add=True, verbose_name='Дата платежа')

    def __str__(self):
        return f'Взнос {self.amount} руб. от {self.sponsor.username} для {self.pet.name}'

    class Meta:
        verbose_name = 'Опекунский взнос'
        verbose_name_plural = 'Опекунские взносы'
        ordering = ['-payment_date']
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name='sponsorship_amount_gt_0'),
        ]


class HomePhotoReport(models.Model):
    contract = models.ForeignKey(
        AdoptionContract, on_delete=models.CASCADE,
        related_name='reports', verbose_name='Договор'
    )
    report_date = models.DateField(auto_now_add=True, verbose_name='Дата отчёта')
    photo = models.ImageField(
        'Фото из дома',
        upload_to='reports/',
        validators=[validate_image_file]
    )
    comment = models.TextField('Комментарий хозяина', blank=True)

    def __str__(self):
        return f'Отчёт по договору #{self.contract_id} от {self.report_date}'

    class Meta:
        verbose_name = 'Фотоотчёт из нового дома'
        verbose_name_plural = 'Фотоотчёты из нового дома'
        ordering = ['-report_date']


class Profile(models.Model):
    GENDER_CHOICES = [('male', 'Мужской'), ('female', 'Женский')]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='profile', verbose_name='Пользователь',
    )
    phone = models.CharField('Телефон', max_length=20, blank=True)
    gender = models.CharField('Пол', max_length=10, choices=GENDER_CHOICES, blank=True)

    def __str__(self):
        return f'Профиль {self.user.username}'

    class Meta:
        verbose_name = 'Профиль пользователя'
        verbose_name_plural = 'Профили пользователей'
