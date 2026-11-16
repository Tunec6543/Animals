from django.shortcuts import render

# Create your views here.
def index(request):
    return render(request, 'index.html', {'pets': range(12)})

def about(request):
    return render(request, 'stub.html', {'title': 'О нас'})


def donate(request):
    return render(request, 'stub.html', {'title': 'Поддержать'})


def staff(request):
    return render(request, 'stub.html', {'title': 'Сотрудникам'})


def login_view(request):
    return render(request, 'stub.html', {'title': 'Войти'})


def register(request):
    return render(request, 'stub.html', {'title': 'Регистрация'})


def profile(request):
    return render(request, 'stub.html', {'title': 'Профиль'})
