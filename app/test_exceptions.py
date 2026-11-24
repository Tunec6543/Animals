from unittest import mock

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.test import Client, TestCase
from django.urls import reverse

from .models import AdoptionApplication, Pet

User = get_user_model()


class ExceptionalSituationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("anna", "a@e.com", "Test#12345")
        cls.pet = Pet.objects.create(name="Рекс", species="dog", age=4, gender="male")

    def test_1_missing_record_returns_404_page(self):
        response = self.client.get(reverse("pet_detail", args=[99999]))
        self.assertContains(response, "404", status_code=404)
        self.assertContains(response, reverse("search"), status_code=404)

    def test_2_no_rights_returns_403_page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("staff"))
        self.assertContains(response, "403", status_code=403)
        self.assertContains(response, reverse("index"), status_code=403)

    def test_3_invalid_form_creates_nothing_and_keeps_input(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("adopt", args=[self.pet.pk]),
            {"housing_conditions": "тесно", "experience": "нет"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(AdoptionApplication.objects.count(), 0)
        self.assertContains(response, "field__error")
        self.assertContains(response, "тесно")

    def test_4_error_in_the_middle_of_operation_changes_nothing(self):
        staff = User.objects.create_user("boss", "b@e.com", "Test#12345", is_staff=True)
        application = AdoptionApplication.objects.create(
            user=self.user, pet=self.pet, housing_conditions="x" * 20, experience="y" * 20
        )
        self.client.force_login(staff)
        with mock.patch("app.models.Pet.objects.filter", side_effect=DatabaseError):
            response = self.client.post(
                reverse("staff_application", args=[application.pk]), {"action": "approve"}
            )
        self.assertRedirects(response, reverse("staff"))
        application.refresh_from_db()
        self.pet.refresh_from_db()
        self.assertEqual(application.status, "pending")
        self.assertEqual(self.pet.status, "available")

    def test_5_empty_selection_does_not_crash(self):
        self.assertEqual(self.client.get(reverse("pet_detail", args=[self.pet.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("donate")).status_code, 200)
        self.assertEqual(self.client.get(reverse("search"), {"q": "нет такого"}).status_code, 200)
        self.client.force_login(self.user)
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Вы пока не делали пожертвований")

    def test_500_page_is_ours(self):
        client = Client(raise_request_exception=False)
        with mock.patch("app.views._filter_pets", side_effect=RuntimeError):
            response = client.get(reverse("index"))
        self.assertContains(response, "Ошибка сервера", status_code=500)
