import logging
import time
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, IntegrityError, transaction
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Avg, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    AdoptionForm,
    ContactForm,
    DonateForm,
    ProfileForm,
    RegisterForm,
    WalkForm,
)
from .models import (
    AdoptionApplication,
    Pet,
    Profile,
    SponsorshipPayment,
    WalkingBooking,
)

logger = logging.getLogger(__name__)

PETS_PER_PAGE = 20

# Возрастные группы каталога: ключ -> (подпись, от, до включительно)
AGE_GROUPS = {
    "0-1": ("До 2 лет", 0, 1),
    "2-5": ("2–5 лет", 2, 5),
    "6+": ("6 лет и старше", 6, None),
}


def _paginate(request, queryset):
    return Paginator(queryset, PETS_PER_PAGE).get_page(request.GET.get("page"))


def _filter_pets(request):
    q = request.GET.get("q", "").strip()
    species = request.GET.get("species", "")
    gender = request.GET.get("gender", "")
    age = request.GET.get("age", "")
    logger.debug(
        "Фильтр каталога: q=%r, species=%r, gender=%r, age=%r", q, species, gender, age
    )
    pets = Pet.objects.all()
    if species in dict(Pet.SPECIES_CHOICES):
        pets = pets.filter(species=species)
    if gender in dict(Pet.GENDER_CHOICES):
        pets = pets.filter(gender=gender)
    if age in AGE_GROUPS:
        _, age_from, age_to = AGE_GROUPS[age]
        pets = pets.filter(age__gte=age_from)
        if age_to is not None:
            pets = pets.filter(age__lte=age_to)
    if "ids" in request.GET:
        # BUG-03: ограничиваем длину числа и количество идентификаторов, иначе SQLite даёт OverflowError (500)
        ids = [
            int(i)
            for i in request.GET["ids"].split(",")[:200]
            if i.isdigit() and len(i) <= 18
        ]
        pets = pets.filter(pk__in=ids)
    if q:
        # SQLite сравнивает кириллицу с учётом регистра, поэтому пробуем разные варианты написания
        variants = {q, q.lower(), q.upper(), q.capitalize()}
        condition = Q()
        for variant in variants:
            condition |= (
                Q(name__icontains=variant)
                | Q(breed__icontains=variant)
                | Q(description__icontains=variant)
            )
        pets = pets.filter(condition)
    return q, species, gender, age, pets


def _catalog_context(request, q, species, gender, age, pets):
    params = request.GET.copy()
    params.pop("page", None)
    return {
        "q": q,
        "species": species,
        "gender": gender,
        "age": age,
        "has_filters": bool(q or species or gender or age),
        "species_choices": Pet.SPECIES_CHOICES,
        "gender_choices": Pet.GENDER_CHOICES,
        "age_choices": [(key, group[0]) for key, group in AGE_GROUPS.items()],
        "page_obj": _paginate(request, pets),
        "query_string": params.urlencode(),
    }


def index(request):
    filters = _filter_pets(request)
    return render(request, "index.html", _catalog_context(request, *filters))


def search(request):
    q, species, gender, age, pets = _filter_pets(request)
    if not (q or species or gender or age):
        pets = Pet.objects.none()
    context = _catalog_context(request, q, species, gender, age, pets)
    return render(request, "search.html", context)


def pets_api(request):
    context = _catalog_context(request, *_filter_pets(request))
    return JsonResponse(
        {
            "html": render_to_string("_catalog_content.html", context, request=request),
            "count": context["page_obj"].paginator.count,
        }
    )


def pet_detail(request, pk):
    pet = get_object_or_404(Pet.objects.select_related("volier"), pk=pk)
    vet_card = getattr(pet, 'vet_card', None)
    total = pet.sponsorships.aggregate(total=Sum("amount"))["total"]
    return render(
        request, "pet_detail.html", {"pet": pet, "vet_card": vet_card, "total": total}
    )


@login_required
def walk_book(request, pk):
    pet = get_object_or_404(Pet, pk=pk)
    if pet.status != "available":
        messages.error(request, "Этот питомец сейчас недоступен для прогулок.")
        return redirect("pet_detail", pk=pet.pk)
    form = WalkForm(request.POST or None, pet=pet)
    if request.method == "POST" and form.is_valid():
        booking = form.save(commit=False)
        booking.volunteer = request.user
        booking.pet = pet
        booking.save()
        logger.info(
            "Запись на прогулку: пользователь=%s, питомец=%s, время=%s",
            request.user.username,
            pet.pk,
            booking.date_time,
        )
        messages.success(request, f"Вы записаны на прогулку с питомцем {pet.name}.")
        return redirect("profile")
    return render(
        request,
        "form_page.html",
        {
            "form": form,
            "title": f"Прогулка с питомцем: {pet.name}",
            "submit": "Записаться",
        },
    )


@login_required
def adopt(request, pk):
    pet = get_object_or_404(Pet, pk=pk)
    if pet.status != "available":
        messages.error(request, "Этот питомец сейчас недоступен для усыновления.")
        return redirect("pet_detail", pk=pet.pk)
    if AdoptionApplication.objects.filter(user=request.user, pet=pet).exists():
        messages.info(request, "Вы уже подавали заявку на этого питомца.")
        return redirect("profile")
    form = AdoptionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        application = form.save(commit=False)
        application.user = request.user
        application.pet = pet
        try:
            with transaction.atomic():
                application.save()
        except IntegrityError:
            # BUG-02: двойная отправка формы — вторая заявка нарушает уникальность (пользователь, питомец)
            messages.info(request, "Вы уже подавали заявку на этого питомца.")
            return redirect("profile")
        logger.info(
            "Заявка на усыновление: пользователь=%s, питомец=%s",
            request.user.username,
            pet.pk,
        )
        messages.success(request, f"Заявка на питомца {pet.name} отправлена.")
        return redirect("profile")
    return render(
        request,
        "form_page.html",
        {
            "form": form,
            "title": f"Заявка на усыновление: {pet.name}",
            "submit": "Отправить заявку",
        },
    )


def register(request):
    if request.user.is_authenticated:
        return redirect("profile")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        logger.info("Зарегистрирован пользователь %s", user.username)
        messages.success(request, "Регистрация прошла успешно.")
        return redirect("profile")
    if request.method == "POST":
        logger.warning(
            "Регистрация отклонена, поля с ошибками: %s", ", ".join(form.errors)
        )
    return render(request, "register.html", {"form": form})


@login_required
def profile(request):
    applications = AdoptionApplication.objects.filter(user=request.user).select_related(
        "pet", "contract"
    )
    walks = WalkingBooking.objects.filter(volunteer=request.user).select_related("pet")
    profile, _ = Profile.objects.get_or_create(user=request.user)
    payments = SponsorshipPayment.objects.filter(sponsor=request.user).select_related(
        "pet"
    )
    donations_total = payments.aggregate(total=Sum("amount"))["total"]
    return render(
        request,
        "profile.html",
        {
            "applications": applications,
            "walks": walks,
            "profile": profile,
            "payments": payments,
            "donations_total": donations_total,
        },
    )


@login_required
@require_POST
def application_cancel(request, pk):
    # BUG-09: пользователь может отменить только свою заявку и только пока она на рассмотрении
    application = get_object_or_404(
        AdoptionApplication, pk=pk, user=request.user, status="pending"
    )
    pet_name = application.pet.name
    application.delete()
    logger.info(
        "Отмена заявки: пользователь=%s, заявка=%s", request.user.username, pk
    )
    messages.success(request, f"Заявка на питомца {pet_name} отменена.")
    return redirect("profile")


@login_required
def profile_edit(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Профиль обновлён.")
        return redirect("profile")
    return render(
        request,
        "form_page.html",
        {
            "form": form,
            "title": "Редактирование профиля",
            "submit": "Сохранить",
            "cancel_url": reverse("profile"),
        },
    )


@login_required
def profile_delete(request):
    if request.method == "POST":
        user = request.user
        logger.info("Удаление профиля пользователя %s", user.username)
        logout(request)
        user.delete()
        messages.success(request, "Ваш профиль удалён.")
        return redirect("index")
    return render(request, "profile_delete.html")


def about(request):
    form = ContactForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        logger.info("Отправка сообщения с сайта: начало")
        started = time.monotonic()
        try:
            send_mail(
                f"Сообщение с сайта от {data['name']}",
                f"{data['message']}\n\nEmail: {data['email']}\nТелефон: {data['phone'] or 'не указан'}",
                data["email"],
                ["shelter@example.com"],
            )
        except Exception:
            logger.exception("Не удалось отправить сообщение с сайта")
            messages.error(request, "Не удалось отправить сообщение. Попробуйте позже.")
            return render(request, "about.html", {"form": form})
        logger.info(
            "Отправка сообщения с сайта: готово за %.2f с", time.monotonic() - started
        )
        messages.success(
            request, "Сообщение отправлено. Мы ответим на указанный email."
        )
        return redirect("about")
    return render(request, "about.html", {"form": form})


def donate(request):
    total = SponsorshipPayment.objects.aggregate(total=Sum("amount"))["total"]
    context = {"total": total}
    if request.user.is_authenticated:
        form = DonateForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            payment = form.save(commit=False)
            payment.sponsor = request.user
            payment.save()
            logger.info(
                "Пожертвование: пользователь=%s, питомец=%s, сумма=%s",
                request.user.username,
                payment.pet.pk,
                payment.amount,
            )
            messages.success(
                request,
                f"Спасибо! Взнос {payment.amount} ₽ для питомца {payment.pet.name} принят.",
            )
            return redirect("donate")
        context["form"] = form
        context["payments"] = SponsorshipPayment.objects.filter(
            sponsor=request.user
        ).select_related("pet")[:10]
    return render(request, "donate.html", context)


def csrf_failure(request, reason=""):
    logger.warning("Ошибка CSRF: адрес=%s, причина=%s", request.path, reason)
    return render(request, "403.html", status=403)


def staff_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            logger.warning(
                "Отказ в доступе: пользователь=%s, адрес=%s",
                request.user.username,
                request.path,
            )
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


@staff_required
def staff(request):
    applications = AdoptionApplication.objects.filter(status="pending").select_related(
        "user", "pet"
    )
    walks = (
        WalkingBooking.objects.filter(is_completed=False, date_time__gte=timezone.now())
        .select_related("pet", "volunteer")
        .order_by("date_time")[:20]
    )
    return render(request, "staff.html", {"applications": applications, "walks": walks})


@staff_required
@require_POST
def staff_application(request, pk):
    application = get_object_or_404(AdoptionApplication, pk=pk, status="pending")
    action = request.POST.get("action")
    logger.info(
        "Сотрудник %s: действие=%s, заявка=%s",
        request.user.username,
        action,
        application.pk,
    )
    if action == "approve":
        if application.pet.status == "reserved":
            messages.error(request, "Питомец уже забронирован другой одобренной заявкой.")
            return redirect("staff")
        application.status = "approved"
        messages.success(request, f"Заявка на питомца {application.pet.name} одобрена.")
    elif action == "reject":
        application.status = "rejected"
        messages.success(
            request, f"Заявка на питомца {application.pet.name} отклонена."
        )
    else:
        logger.warning("Неизвестное действие %r для заявки %s", action, application.pk)
        messages.error(request, "Неизвестное действие.")
        return redirect("staff")
    try:
        # Статус заявки и бронь питомца сохраняются вместе или не сохраняются совсем
        with transaction.atomic():
            application.save()
    except DatabaseError:
        logger.exception("Не удалось сохранить решение по заявке %s", application.pk)
        messages.error(request, "Не удалось сохранить решение. Попробуйте позже.")
    return redirect("staff")
