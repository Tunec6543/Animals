from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from .forms import RegisterForm
from .models import AdoptionApplication, Pet

PETS_PER_PAGE = 20


def _paginate(request, queryset):
    return Paginator(queryset, PETS_PER_PAGE).get_page(request.GET.get('page'))


def index(request):
    pets = Pet.objects.all()
    return render(request, 'index.html', {'page_obj': _paginate(request, pets)})


def search(request):
    q = request.GET.get('q', '').strip()
    pets = Pet.objects.none()
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
        pets = Pet.objects.filter(condition)
    return render(request, 'search.html', {'q': q, 'page_obj': _paginate(request, pets)})


def pet_detail(request, pk):
    pet = get_object_or_404(Pet.objects.select_related('volier'), pk=pk)
    vet_card = getattr(pet, 'vet_card', None)
    total = pet.sponsorships.aggregate(total=Sum('amount'))['total']
    return render(request, 'pet_detail.html', {'pet': pet, 'vet_card': vet_card, 'total': total})


def walk_book(request, pk):
    pet = get_object_or_404(Pet, pk=pk)
    return render(request, 'stub.html', {'title': f'Прогулка с питомцем: {pet.name}'})


def adopt(request, pk):
    pet = get_object_or_404(Pet, pk=pk)
    return render(request, 'stub.html', {'title': f'Договор: {pet.name}'})


def register(request):
    if request.user.is_authenticated:
        return redirect('profile')
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        return redirect('profile')
    return render(request, 'register.html', {'form': form})


@login_required
def profile(request):
    applications = (
        AdoptionApplication.objects.filter(user=request.user)
        .select_related('pet', 'contract')
    )
    return render(request, 'profile.html', {'applications': applications})


def about(request):
    return render(request, 'about.html')


def donate(request):
    return render(request, 'stub.html', {'title': 'Поддержать'})


def staff(request):
    return render(request, 'stub.html', {'title': 'Сотрудникам'})
