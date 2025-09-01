from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('',views.login_user, name = 'login-user'),
    path('logout-user/',views.logout_user, name = 'logout'),
    path('verify-email/<str:token>/', views.verify_email, name='verify_email'),
    path('register-user/',views.register, name = 'register'),
    path('register/<uuid:token>/', views.register_with_invitation, name='register_with_invitation'),
    
    path('password-reset/', views.CustomPasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', views.CustomPasswordResetDoneView.as_view(), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', views.CustomPasswordResetConfirmView.as_view(), name='password_reset_confirm'), 
    path('reset/done/', views.CustomPasswordResetCompleteView.as_view(), name='password_reset_complete'),
]
