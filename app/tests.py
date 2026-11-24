from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Pet


class SiteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        for i in range(45):
            Pet.objects.create(name=f"Питомец {i}", species="dog", age=3, gender="male")
        Pet.objects.create(
            name="Барсик", species="cat", breed="Сибирская", age=2, gender="male"
        )
        cls.user = get_user_model().objects.create_user(
            "tester", "t@example.com", "pass-12345-x"
        )

    def test_catalog_paginates_by_20(self):
        response = self.client.get(reverse("index"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["page_obj"]), 20)
        last = self.client.get(reverse("index"), {"page": 3})
        self.assertEqual(len(last.context["page_obj"]), 6)

    def test_pet_detail(self):
        pet = Pet.objects.get(name="Барсик")
        response = self.client.get(reverse("pet_detail", args=[pet.pk]))
        self.assertContains(response, "Барсик")
        self.assertEqual(
            self.client.get(reverse("pet_detail", args=[99999])).status_code, 404
        )

    def test_search_is_case_insensitive_for_cyrillic(self):
        response = self.client.get(reverse("search"), {"q": "барсик"})
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        empty = self.client.get(reverse("search"), {"q": "нет такого"})
        self.assertIn("ничего не найдено", empty.content.decode("utf-8").lower())

    def test_profile_requires_login(self):
        response = self.client.get(reverse("profile"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('profile')}")
        self.client.login(username="tester", password="pass-12345-x")
        self.assertContains(self.client.get(reverse("profile")), "tester")

    def test_register_creates_user_and_logs_in(self):
        response = self.client.post(
            reverse("register"),
            {
                "last_name": "Иванов",
                "first_name": "Иван",
                "username": "newbie",
                "email": "new@example.com",
                "phone": "+7 900 000-00-00",
                "password": "Str0ng-pass-2026",
                "password2": "Str0ng-pass-2026",
            },
        )
        self.assertRedirects(response, reverse("profile"))
        user = get_user_model().objects.get(username="newbie")
        self.assertEqual(user.profile.phone, "+7 900 000-00-00")
        self.assertEqual(user.get_full_name(), "Иван Иванов")

    def test_register_password_mismatch(self):
        response = self.client.post(
            reverse("register"),
            {
                "last_name": "Иванов",
                "first_name": "Иван",
                "username": "mismatch",
                "email": "m@example.com",
                "phone": "+7 900 000-00-00",
                "password": "Str0ng-pass-2026",
                "password2": "Other-pass-2026",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Пароли не совпадают")
        self.assertFalse(get_user_model().objects.filter(username="mismatch").exists())

    def test_cancel_own_pending_application_only(self):
        from .models import AdoptionApplication

        pet = Pet.objects.get(name="Барсик")
        other = get_user_model().objects.create_user("other", "o@example.com", "pass-12345-x")
        mine = AdoptionApplication.objects.create(
            user=self.user, pet=pet, housing_conditions="x" * 20, experience="y" * 20
        )
        foreign = AdoptionApplication.objects.create(
            user=other, pet=Pet.objects.exclude(pk=pet.pk).first(),
            housing_conditions="x" * 20, experience="y" * 20,
        )
        self.client.force_login(self.user)
        self.assertEqual(
            self.client.post(reverse("application_cancel", args=[foreign.pk])).status_code, 404
        )
        self.assertTrue(AdoptionApplication.objects.filter(pk=foreign.pk).exists())
        self.assertEqual(self.client.get(reverse("application_cancel", args=[mine.pk])).status_code, 405)
        response = self.client.post(reverse("application_cancel", args=[mine.pk]))
        self.assertRedirects(response, reverse("profile"))
        self.assertFalse(AdoptionApplication.objects.filter(pk=mine.pk).exists())

    def test_register_shows_errors(self):
        response = self.client.post(
            reverse("register"),
            {
                "username": "x",
                "email": "t@example.com",
                "password": "123",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "field__error")

    def test_static_pages(self):
        for name in ("about", "donate", "login", "register"):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

        # Гость не должен попадать в раздел сотрудников
        response = self.client.get(reverse("staff"))
        self.assertEqual(response.status_code, 302)

        # Сотрудник должен иметь доступ
        staff_user = get_user_model().objects.create_user(
            username="staff_test", password="Strong-test-pass-2026", is_staff=True
        )
        self.client.force_login(staff_user)

        response = self.client.get(reverse("staff"))
        self.assertEqual(response.status_code, 200)


class DonationRangeTests(TestCase):
    """BUG-05: сумма пожертвования — от 50 до 100 000 ₽ включительно."""

    def setUp(self):
        self.pet = Pet.objects.create(name="Рекс", species="dog", age=4, gender="male")
        self.client.force_login(
            get_user_model().objects.create_user("donor", "d@example.com", "Test#12345")
        )

    def _donate(self, amount):
        from .models import SponsorshipPayment

        before = SponsorshipPayment.objects.count()
        response = self.client.post(
            reverse("donate"),
            {"pet": self.pet.pk, "amount": amount, "payment_type": "sbp", "comment": ""},
        )
        return SponsorshipPayment.objects.count() - before, response

    def test_boundaries(self):
        for value, created in (("49", 0), ("50", 1), ("100000", 1), ("100001", 0)):
            with self.subTest(value=value):
                self.assertEqual(self._donate(value)[0], created)

    def test_error_message_is_shown(self):
        self.assertContains(self._donate("10")[1], "Минимальная сумма взноса — 50 ₽.")
        self.assertContains(self._donate("200000")[1], "Максимальная сумма взноса")

    def test_model_validators(self):
        from django.core.exceptions import ValidationError

        from .models import SponsorshipPayment

        payment = SponsorshipPayment(
            sponsor=get_user_model().objects.get(username="donor"),
            pet=self.pet, amount=10, payment_type="card",
        )
        with self.assertRaises(ValidationError):
            payment.full_clean()


class CatalogFilterTests(TestCase):
    """BUG-08: фильтры каталога по полу и возрасту (размера у питомца нет)."""

    @classmethod
    def setUpTestData(cls):
        Pet.objects.create(name="Дик", species="dog", age=1, gender="male")
        Pet.objects.create(name="Мурка", species="cat", age=3, gender="female")
        Pet.objects.create(name="Бим", species="dog", age=8, gender="male")

    def _names(self, **params):
        response = self.client.get(reverse("index"), params)
        return sorted(pet.name for pet in response.context["page_obj"])

    def test_gender(self):
        self.assertEqual(self._names(gender="female"), ["Мурка"])
        self.assertEqual(self._names(gender="male"), ["Бим", "Дик"])

    def test_age_groups(self):
        self.assertEqual(self._names(age="0-1"), ["Дик"])
        self.assertEqual(self._names(age="2-5"), ["Мурка"])
        self.assertEqual(self._names(age="6+"), ["Бим"])

    def test_combined_and_invalid_values(self):
        self.assertEqual(self._names(gender="male", age="6+"), ["Бим"])
        self.assertEqual(len(self._names(gender="x", age="y")), 3)

    def test_api_and_search_use_filters(self):
        api = self.client.get(reverse("pets_api"), {"gender": "female"})
        self.assertEqual(api.json()["count"], 1)
        search = self.client.get(reverse("search"), {"age": "6+"})
        self.assertEqual(search.context["page_obj"].paginator.count, 1)

    def test_no_size_field(self):
        self.assertNotIn("size", [f.name for f in Pet._meta.get_fields()])


class ProfileDonationHistoryTests(TestCase):
    def setUp(self):
        from .models import SponsorshipPayment

        self.user = get_user_model().objects.create_user("donor", "d@example.com", "Test#12345")
        other = get_user_model().objects.create_user("other", "o@example.com", "Test#12345")
        pet = Pet.objects.create(name="Рекс", species="dog", age=4, gender="male")
        SponsorshipPayment.objects.create(sponsor=self.user, pet=pet, amount=500, payment_type="sbp")
        SponsorshipPayment.objects.create(sponsor=self.user, pet=pet, amount=250, payment_type="card")
        SponsorshipPayment.objects.create(sponsor=other, pet=pet, amount=9999, payment_type="cash")

    def test_section_shows_only_own_payments_and_total(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("profile"))
        self.assertContains(response, "История пожертвований")
        self.assertEqual(len(response.context["payments"]), 2)
        self.assertContains(response, "Всего пожертвовано: 750,00")
        self.assertNotContains(response, "9999")

    def test_empty_history(self):
        self.client.force_login(
            get_user_model().objects.create_user("new", "n@example.com", "Test#12345")
        )
        self.assertContains(self.client.get(reverse("profile")), "Вы пока не делали пожертвований")
