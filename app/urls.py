from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from . import views
from .forms import LoginForm

urlpatterns = [
    path('', views.index, name='index'),
    path('search/', views.search, name='search'),
    path('pets/<int:pk>/', views.pet_detail, name='pet_detail'),
    path('pets/<int:pk>/walk/', views.walk_book, name='walk_book'),
    path('pets/<int:pk>/adopt/', views.adopt, name='adopt'),
    path('about/', views.about, name='about'),
    path('donate/', views.donate, name='donate'),
    path('staff/', views.staff, name='staff'),
    path('login/', LoginView.as_view(
        template_name='login.html',
        authentication_form=LoginForm,
        redirect_authenticated_user=True,
    ), name='login'),
    path('register/', views.register, name='register'),
    path('profile/', views.profile, name='profile'),
    path('logout/', LogoutView.as_view(), name='logout'),
]
