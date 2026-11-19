from functools import wraps

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import AdoptionForm, ContactForm, DonateForm, ProfileForm, RegisterForm, WalkForm
from .models import AdoptionApplication, Pet, Profile, SponsorshipPayment, WalkingBooking

PETS_PER_PAGE = 20


def _paginate(request, queryset):
    return Paginator(queryset, PETS_PER_PAGE).get_page(request.GET.get('page'))


def _filter_pets(request):
    q = request.GET.get('q', '').strip()
    species = request.GET.get('species', '')
    pets = Pet.objects.all()
    if species in dict(Pet.SPECIES_CHOICES):
        pets = pets.filter(species=species)
    if 'ids' in request.GET:
        ids = [int(i) for i in request.GET['ids'].split(',') if i.isdigit()]
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
    return q, species, pets


def _catalog_context(request, q, species, pets):
    params = request.GET.copy()
    params.pop('page', None)
    return {
        'q': q,
        'species': species,
        'species_choices': Pet.SPECIES_CHOICES,
        'page_obj': _paginate(request, pets),
        'query_string': params.urlencode(),
    }


def index(request):
    q, species, pets = _filter_pets(request)
    return render(request, 'index.html', _catalog_context(request, q, species, pets))


def search(request):
    q, species, pets = _filter_pets(request)
    if not q and not species:
        pets = Pet.objects.none()
    return render(request, 'search.html', _catalog_context(request, q, species, pets))


def pets_api(request):
    q, species, pets = _filter_pets(request)
    context = _catalog_context(request, q, species, pets)
    return JsonResponse({
        'html': render_to_string('_catalog_content.html', context, request=request),
        'count': context['page_obj'].paginator.count,
    })


def pet_detail(request, pk):
    pet = get_object_or_404(Pet.objects.select_related('volier'), pk=pk)
    vet_card = getattr(pet, 'vet_card', None)
    total = pet.sponsorships.aggregate(total=Sum('amount'))['total']
    return render(request, 'pet_detail.html', {'pet': pet, 'vet_card': vet_card, 'total': total})


@login_required
def walk_book(request, pk):
    pet = get_object_or_404(Pet, pk=pk)
    if pet.status != 'available':
        messages.error(request, 'Этот питомец сейчас недоступен для прогулок.')
        return redirect('pet_detail', pk=pet.pk)
    form = WalkForm(request.POST or None, pet=pet)
    if request.method == 'POST' and form.is_valid():
        booking = form.save(commit=False)
        booking.volunteer = request.user
        booking.pet = pet
        booking.save()
        messages.success(request, f'Вы записаны на прогулку с питомцем {pet.name}.')
        return redirect('profile')
    return render(request, 'form_page.html', {
        'form': form, 'title': f'Прогулка с питомцем: {pet.name}', 'submit': 'Записаться',
    })


@login_required
def adopt(request, pk):
    pet = get_object_or_404(Pet, pk=pk)
    if pet.status != 'available':
        messages.error(request, 'Этот питомец сейчас недоступен для усыновления.')
        return redirect('pet_detail', pk=pet.pk)
    if AdoptionApplication.objects.filter(user=request.user, pet=pet).exists():
        messages.info(request, 'Вы уже подавали заявку на этого питомца.')
        return redirect('profile')
    form = AdoptionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        application = form.save(commit=False)
        application.user = request.user
        application.pet = pet
        application.save()
        messages.success(request, f'Заявка на питомца {pet.name} отправлена.')
        return redirect('profile')
    return render(request, 'form_page.html', {
        'form': form, 'title': f'Заявка на усыновление: {pet.name}', 'submit': 'Отправить заявку',
    })


def register(request):
    if request.user.is_authenticated:
        return redirect('profile')
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, 'Регистрация прошла успешно.')
        return redirect('profile')
    return render(request, 'register.html', {'form': form})


@login_required
def profile(request):
    applications = (
        AdoptionApplication.objects.filter(user=request.user)
        .select_related('pet', 'contract')
    )
    walks = WalkingBooking.objects.filter(volunteer=request.user).select_related('pet')
    profile, _ = Profile.objects.get_or_create(user=request.user)
    return render(request, 'profile.html', {
        'applications': applications, 'walks': walks, 'profile': profile,
    })


@login_required
def profile_edit(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Профиль обновлён.')
        return redirect('profile')
    return render(request, 'form_page.html', {
        'form': form, 'title': 'Редактирование профиля', 'submit': 'Сохранить',
    })


@login_required
def profile_delete(request):
    if request.method == 'POST':
        user = request.user
        logout(request)
        user.delete()
        messages.success(request, 'Ваш профиль удалён.')
        return redirect('index')
    return render(request, 'profile_delete.html')


def about(request):
    form = ContactForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        send_mail(
            f'Сообщение с сайта от {data["name"]}',
            f'{data["message"]}\n\nEmail: {data["email"]}\nТелефон: {data["phone"] or "не указан"}',
            data['email'],
            ['shelter@example.com'],
        )
        messages.success(request, 'Сообщение отправлено. Мы ответим на указанный email.')
        return redirect('about')
    return render(request, 'about.html', {'form': form})


def donate(request):
    total = SponsorshipPayment.objects.aggregate(total=Sum('amount'))['total']
    context = {'total': total}
    if request.user.is_authenticated:
        form = DonateForm(request.POST or None)
        if request.method == 'POST' and form.is_valid():
            payment = form.save(commit=False)
            payment.sponsor = request.user
            payment.save()
            messages.success(request, f'Спасибо! Взнос {payment.amount} ₽ для питомца {payment.pet.name} принят.')
            return redirect('donate')
        context['form'] = form
        context['payments'] = SponsorshipPayment.objects.filter(sponsor=request.user).select_related('pet')[:10]
    return render(request, 'donate.html', context)


def staff_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            messages.error(request, 'Раздел доступен только сотрудникам приюта.')
            return redirect('index')
        return view(request, *args, **kwargs)
    return wrapper


@staff_required
def staff(request):
    applications = AdoptionApplication.objects.filter(status='pending').select_related('user', 'pet')
    walks = WalkingBooking.objects.filter(
        is_completed=False, date_time__gte=timezone.now()
    ).select_related('pet', 'volunteer').order_by('date_time')[:20]
    return render(request, 'staff.html', {'applications': applications, 'walks': walks})


@staff_required
@require_POST
def staff_application(request, pk):
    application = get_object_or_404(AdoptionApplication, pk=pk, status='pending')
    action = request.POST.get('action')
    if action == 'approve':
        application.status = 'approved'
        messages.success(request, f'Заявка на питомца {application.pet.name} одобрена.')
    elif action == 'reject':
        application.status = 'rejected'
        messages.success(request, f'Заявка на питомца {application.pet.name} отклонена.')
    else:
        messages.error(request, 'Неизвестное действие.')
        return redirect('staff')
    application.save()
    return redirect('staff')
