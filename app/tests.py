from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Pet


class SiteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for i in range(45):
            Pet.objects.create(name=f'Питомец {i}', species='dog', age=3, gender='male')
        Pet.objects.create(name='Барсик', species='cat', breed='Сибирская', age=2, gender='male')
        cls.user = get_user_model().objects.create_user('tester', 't@example.com', 'pass-12345-x')

    def test_catalog_paginates_by_20(self):
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj']), 20)
        last = self.client.get(reverse('index'), {'page': 3})
        self.assertEqual(len(last.context['page_obj']), 6)

    def test_pet_detail(self):
        pet = Pet.objects.get(name='Барсик')
        response = self.client.get(reverse('pet_detail', args=[pet.pk]))
        self.assertContains(response, 'Барсик')
        self.assertEqual(self.client.get(reverse('pet_detail', args=[99999])).status_code, 404)

    def test_search_is_case_insensitive_for_cyrillic(self):
        response = self.client.get(reverse('search'), {'q': 'барсик'})
        self.assertEqual(response.context['page_obj'].paginator.count, 1)
        empty = self.client.get(reverse('search'), {'q': 'нет такого'})
        self.assertContains(empty, 'ничего не найдено')

    def test_profile_requires_login(self):
        response = self.client.get(reverse('profile'))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('profile')}")
        self.client.login(username='tester', password='pass-12345-x')
        self.assertContains(self.client.get(reverse('profile')), 'tester')

    def test_register_creates_user_and_logs_in(self):
        response = self.client.post(reverse('register'), {
            'username': 'newbie', 'email': 'new@example.com', 'password': 'Str0ng-pass-2026',
        })
        self.assertRedirects(response, reverse('profile'))
        self.assertTrue(get_user_model().objects.filter(username='newbie').exists())

    def test_register_shows_errors(self):
        response = self.client.post(reverse('register'), {
            'username': 'x', 'email': 't@example.com', 'password': '123',
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'field__error')

    def test_static_pages(self):
        for name in ('about', 'donate', 'staff', 'login', 'register'):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
