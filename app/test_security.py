"""Занятие 15, часть 2: проверки безопасности (локальный проект, тестовая БД)."""
import io

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse
from PIL import Image

from .models import AdoptionApplication, Pet, SponsorshipPayment

User = get_user_model()
XSS = '<script>alert(1)</script>'
PWD = 'Str0ng-pass-2026'


def png_bytes():
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), 'red').save(buf, 'PNG')
    return buf.getvalue()


class SecurityChecks(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.anna = User.objects.create_user('anna', 'anna@e.com', PWD)
        cls.ivan = User.objects.create_user('ivan', 'ivan@e.com', PWD)
        cls.admin = User.objects.create_user('boss', 'boss@e.com', PWD, is_staff=True, is_superuser=True)
        cls.pet = Pet.objects.create(name='Барсик', species='cat', age=2, gender='male')
        cls.app_ivan = AdoptionApplication.objects.create(
            user=cls.ivan, pet=cls.pet, housing_conditions='x' * 25, experience='y' * 25)

    # 1. CSRF
    def test_1_csrf(self):
        c = Client(enforce_csrf_checks=True)
        c.force_login(self.anna)
        r = c.post(reverse('adopt', args=[self.pet.pk]),
                   {'housing_conditions': 'x' * 25, 'experience': 'y' * 25})
        self.assertEqual(r.status_code, 403)
        r = c.post(reverse('profile_delete'))
        self.assertEqual(r.status_code, 403)
        self.assertTrue(User.objects.filter(username='anna').exists())

    # 2. XSS
    def test_2_xss(self):
        self.client.force_login(self.anna)
        self.client.post(reverse('profile_edit'), {'first_name': XSS, 'last_name': 'Т', 'email': 'anna@e.com'})
        html = self.client.get(reverse('profile')).content.decode()
        self.assertNotIn(XSS, html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        Pet.objects.filter(pk=self.pet.pk).update(description=XSS, name=XSS)
        html = self.client.get(reverse('pet_detail', args=[self.pet.pk])).content.decode()
        self.assertNotIn(XSS, html)
        html = self.client.get(reverse('search'), {'q': XSS}).content.decode()
        self.assertNotIn(XSS, html)
        self.assertNotIn('<script>alert(1)', self.client.get(reverse('pets_api'), {'q': XSS}).json()['html'])
        self.client.post(reverse('donate'), {'pet': self.pet.pk, 'amount': 100,
                                             'payment_type': SponsorshipPayment.PAYMENT_CHOICES[0][0],
                                             'comment': XSS})
        self.assertNotIn(XSS, self.client.get(reverse('donate')).content.decode())
        self.client.force_login(self.admin)
        self.assertNotIn(XSS, self.client.get(reverse('staff')).content.decode())

    # 3. SQL-инъекция
    def test_3_sqli(self):
        for url, param in (('search', 'q'), ('index', 'q'), ('index', 'species'), ('index', 'ids'), ('pets_api', 'q')):
            r = self.client.get(reverse(url), {param: "' OR 1=1 --"})
            self.assertEqual(r.status_code, 200, (url, param))
        r = self.client.get(reverse('search'), {'q': "' OR 1=1 --"})
        self.assertEqual(r.context['page_obj'].paginator.count, 0)

    # 4. IDOR / доступ
    def test_4_idor(self):
        self.client.force_login(self.anna)
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        self.assertEqual(self.client.get(reverse('staff')).status_code, 403)
        r = self.client.post(reverse('staff_application', args=[self.app_ivan.pk]), {'action': 'approve'})
        self.assertEqual(r.status_code, 403)
        self.app_ivan.refresh_from_db()
        self.assertEqual(self.app_ivan.status, 'pending')
        self.assertNotIn('ivan', self.client.get(reverse('profile')).content.decode())
        anon = Client()
        self.assertEqual(anon.get(reverse('profile')).status_code, 302)
        self.assertEqual(anon.get(reverse('staff')).status_code, 302)

    # 5. Пароли
    def test_5_passwords(self):
        self.assertTrue(self.anna.password.startswith('pbkdf2_sha256$'))
        self.assertNotIn(PWD, self.anna.password)
        self.assertEqual(len(settings.AUTH_PASSWORD_VALIDATORS), 4)
        r = self.client.post(reverse('register'), {'last_name': 'Нео', 'first_name': 'Нео', 'username': 'neo', 'email': 'n@e.com', 'phone': '+7 900 000-00-00', 'password': '12345678', 'password2': '12345678'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username='neo').exists())
        r = self.client.post(reverse('register'), {'last_name': 'Нео', 'first_name': 'Нео', 'username': 'neo_user', 'email': 'n2@e.com', 'phone': '+7 900 000-00-00', 'password': 'neo_user_2026', 'password2': 'neo_user_2026'})
        self.assertEqual(r.status_code, 200, 'пароль, похожий на логин, отклоняется')
        self.assertFalse(User.objects.filter(username='neo_user').exists())

    # 6. Конфигурация
    def test_6_config(self):
        self.assertFalse(settings.DEBUG, 'DEBUG=True')
        self.assertFalse(settings.SECRET_KEY.startswith('django-insecure'), 'SECRET_KEY в коде')
        self.assertTrue(settings.ALLOWED_HOSTS)

    # 7. Загрузка файлов
    def test_7_upload(self):
        from django.forms import modelform_factory
        PetForm = modelform_factory(Pet, fields=('name', 'species', 'age', 'gender', 'photo'))

        def check(name, content, ctype='image/png'):
            form = PetForm({'name': 'T', 'species': 'dog', 'age': 1, 'gender': 'male'},
                           {'photo': SimpleUploadedFile(name, content, ctype)})
            return 'принят' if form.is_valid() else 'отклонён'
        res = {
            'shell.php (текст)': check('shell.php', b'<?php system($_GET[0]); ?>', 'application/x-php'),
            'virus.exe': check('virus.exe', b'MZ' + b'\0' * 50, 'application/octet-stream'),
            'shell.php.png (php внутри)': check('shell.php.png', b'<?php echo 1; ?>'),
            'photo.php.png (настоящий PNG)': check('photo.php.png', png_bytes()),
            'ok.png': check('ok.png', png_bytes()),
            '6 МБ': check('big.png', png_bytes() + b'\0' * (6 * 1024 * 1024)),
        }
        print('\nUPLOAD:', res)
        self.assertEqual(res['shell.php (текст)'], 'отклонён')
        self.assertEqual(res['virus.exe'], 'отклонён')
        self.assertEqual(res['shell.php.png (php внутри)'], 'отклонён')
        self.assertEqual(res['ok.png'], 'принят')
        self.assertEqual(res['6 МБ'], 'отклонён')

    # 8. Перебор пароля
    def test_8_bruteforce(self):
        from django.core.cache import cache
        cache.clear()
        for _ in range(5):
            self.client.post(reverse('login'), {'username': 'anna', 'password': 'wrong'})
        r = self.client.post(reverse('login'), {'username': 'anna', 'password': PWD})
        self.assertEqual(r.status_code, 200, 'после 5 неверных попыток верный пароль тоже отклоняется')
        self.assertContains(r, 'Слишком много неудачных попыток')
        cache.clear()
        r = self.client.post(reverse('login'), {'username': 'anna', 'password': PWD})
        self.assertEqual(r.status_code, 302)
