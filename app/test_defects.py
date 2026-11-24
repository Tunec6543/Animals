from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import AdoptionApplication, Pet

User = get_user_model()
FORM = {
    'housing_conditions': 'Живу в квартире, есть опыт содержания',
    'experience': 'Опыт содержания кошек более трёх лет',
}


class Bug01ReservationTests(TestCase):
    """BUG-01: одобренная заявка бронирует питомца."""

    def setUp(self):
        self.pet = Pet.objects.create(name='Рекс', species='dog', age=4, gender='male')
        self.anna = User.objects.create_user('anna', 'a@e.com', 'Test#12345')
        self.ivan = User.objects.create_user('ivan', 'i@e.com', 'Test#12345')
        self.staff = User.objects.create_user('staff', 's@e.com', 'Test#12345', is_staff=True)
        self.app = AdoptionApplication.objects.create(user=self.anna, pet=self.pet, **FORM)

    def test_approve_reserves_pet(self):
        self.client.force_login(self.staff)
        self.client.post(reverse('staff_application', args=[self.app.pk]), {'action': 'approve'})
        self.pet.refresh_from_db()
        self.assertEqual(self.pet.status, 'reserved')

    def test_other_user_cannot_apply_for_reserved_pet(self):
        self.client.force_login(self.staff)
        self.client.post(reverse('staff_application', args=[self.app.pk]), {'action': 'approve'})
        self.client.force_login(self.ivan)
        self.client.post(reverse('adopt', args=[self.pet.pk]), FORM)
        self.assertFalse(AdoptionApplication.objects.filter(user=self.ivan).exists())

    def test_reject_keeps_pet_available(self):
        self.client.force_login(self.staff)
        self.client.post(reverse('staff_application', args=[self.app.pk]), {'action': 'reject'})
        self.pet.refresh_from_db()
        self.assertEqual(self.pet.status, 'available')


class Bug02DoubleSubmitTests(TestCase):
    """BUG-02: гонка при двойной отправке формы не должна давать ошибку 500."""

    def test_integrity_error_on_save_is_handled(self):
        from unittest import mock

        pet = Pet.objects.create(name='Мурка', species='cat', age=1, gender='female')
        user = User.objects.create_user('anna', 'a@e.com', 'Test#12345')
        self.client.force_login(user)
        with mock.patch.object(AdoptionApplication, 'save', side_effect=__import__('django').db.IntegrityError):
            response = self.client.post(reverse('adopt', args=[pet.pk]), FORM)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(AdoptionApplication.objects.count(), 0)


class Bug03IdsOverflowTests(TestCase):
    """BUG-03: гигантское значение ids не должно приводить к ошибке 500."""

    def test_huge_ids_do_not_crash(self):
        Pet.objects.create(name='Рекс', species='dog', age=4, gender='male')
        for url in ('/api/pets/?ids=99999999999999999999', '/?ids=' + '9' * 5000, '/search/?q=a&ids=99999999999999999999999999'):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)


class Bug04ProfileEmailTests(TestCase):
    """BUG-04: в профиле нельзя указать email другого пользователя."""

    def setUp(self):
        self.anna = User.objects.create_user('anna', 'anna@example.com', 'Test#12345')
        User.objects.create_user('ivan', 'ivan@example.com', 'Test#12345')
        self.client.force_login(self.anna)

    def _post(self, email):
        return self.client.post(reverse('profile_edit'), {
            'last_name': 'Петрова', 'first_name': 'Анна', 'email': email, 'phone': '', 'gender': '',
        })

    def test_duplicate_email_rejected(self):
        response = self._post('IVAN@example.com')
        self.assertEqual(response.status_code, 200)
        self.anna.refresh_from_db()
        self.assertEqual(self.anna.email, 'anna@example.com')

    def test_own_email_accepted(self):
        self.assertEqual(self._post('anna@example.com').status_code, 302)


class Bug06IntegerAmountTests(TestCase):
    """BUG-06: сумма пожертвования — только целое число рублей."""

    def setUp(self):
        self.pet = Pet.objects.create(name='Рекс', species='dog', age=4, gender='male')
        self.client.force_login(User.objects.create_user('anna', 'a@e.com', 'Test#12345'))

    def _donate(self, amount):
        from .models import SponsorshipPayment
        before = SponsorshipPayment.objects.count()
        self.client.post(reverse('donate'), {'pet': self.pet.pk, 'amount': amount, 'payment_type': 'sbp', 'comment': ''})
        return SponsorshipPayment.objects.count() - before

    def test_fractional_rejected(self):
        for value in ('150.5', '150,5', 'abc', '<b>1</b>'):
            with self.subTest(value=value):
                self.assertEqual(self._donate(value), 0)

    def test_integer_accepted(self):
        self.assertEqual(self._donate('500'), 1)


class Bug10PhotoTests(TestCase):
    def test_validator_rejects_big_and_fake_images(self):
        import io

        from django.core.exceptions import ValidationError
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image

        from .validators import validate_image_file

        buf = io.BytesIO()
        Image.new('RGB', (4, 4)).save(buf, 'PNG')
        validate_image_file(SimpleUploadedFile('ok.png', buf.getvalue(), 'image/png'))
        for name, data in (
            ('big.png', buf.getvalue() + b'\0' * (6 * 1024 * 1024)),
            ('fake.png', b'<?php echo 1; ?>'),
            ('shell.php', buf.getvalue()),
            ('a.php.png', buf.getvalue()),
        ):
            with self.assertRaises(ValidationError, msg=name):
                validate_image_file(SimpleUploadedFile(name, data, 'image/png'))


class Bug11PhoneTests(TestCase):
    def test_garbage_phone_rejected_and_normal_accepted(self):
        from .forms import ContactForm

        base = {'name': 'Иван', 'email': 'i@e.com', 'message': 'Сообщение из десяти символов'}
        for phone in ('----------', '(((((((((('):
            self.assertFalse(ContactForm({**base, 'phone': phone}).is_valid(), phone)
        spaces = ContactForm({**base, 'phone': '          '})
        self.assertTrue(spaces.is_valid())
        self.assertEqual(spaces.cleaned_data['phone'], '')  # необязательное поле: пробелы не сохраняются
        for phone in ('8(900)000-00-00', '+7 900 000-00-00'):
            self.assertTrue(ContactForm({**base, 'phone': phone}).is_valid(), phone)


class Bug12CancelButtonTests(TestCase):
    def test_profile_edit_has_cancel_link(self):
        user = User.objects.create_user('cancel', 'c@e.com', 'pass-12345-x')
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse('profile_edit')), 'Отмена')


class Bug14StaffLinkTests(TestCase):
    def test_staff_link_hidden_for_non_staff(self):
        self.assertNotContains(self.client.get(reverse('index')), 'Сотрудникам')
        user = User.objects.create_user('plain', 'p@e.com', 'pass-12345-x')
        self.client.force_login(user)
        self.assertNotContains(self.client.get(reverse('index')), 'Сотрудникам')
        staff = User.objects.create_user('st', 's@e.com', 'pass-12345-x', is_staff=True)
        self.client.force_login(staff)
        self.assertContains(self.client.get(reverse('index')), 'Сотрудникам')
