from django.shortcuts import get_object_or_404, render,redirect
from django.contrib.auth import login,authenticate,logout
from django.contrib import messages
from .forms import UserRegistrationForm
from django.utils.crypto import get_random_string
from django.urls import reverse
from django.conf import settings
from django.templatetags.static import static
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from . models import VerificationToken

# Create your views here.
def create_verification_token(user):
    token = get_random_string(64)
    VerificationToken.objects.create(user=user, token=token)
    return token

def send_verification_email(user, request):
    token = create_verification_token(user)  # Generate a unique token
    
    # Generate the full verification link
    verification_link = f"{settings.BASE_URL}{reverse('accounts:verify_email', args=[token])}"
    
    # Get the absolute URL for the logo
    logo_url = f"{settings.BASE_URL}/static/accounts/assets/img/logo.png"

    # Render the email template with the context
    subject = 'Verify Your Email Address'
    html_content = render_to_string('accounts/email_verification.html', {
        'user': user,
        'verification_link': verification_link,
        'logo_url': logo_url,
    })

    # Set up sender and recipient information
    from_email = 'williamdemo01@gmail.com'
    sender_name = 'Support'

    # Create and send the email
    email = EmailMultiAlternatives(
        subject,
        '',
        f'{sender_name} <{from_email}>',
        [user.email],
    )
    email.attach_alternative(html_content, "text/html")
    email.send()

## view to log in a user
def login_user(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            #redirect
            return redirect('solicitations:home')

        else:
            #redirect
            messages.success(request,'There was an error loggin in, Try again latter!')
            return redirect('accounts:login-user')
    
    else:
        #
        return render(request,'accounts/login.html')

## view to log out a user
def logout_user(request):
    logout(request)
    return redirect('accounts:login-user')


    #verification view
def verify_email(request, token):
    # Get the verification token and associated user
    verification_token = get_object_or_404(VerificationToken, token=token)
    user = verification_token.user
    user.is_email_verified = True  # Mark the email as verified
    user.save()

    # You can delete the token after verification if needed
    verification_token.delete()

    messages.success(request, "Your email has been verified! You can now log in.")
    return redirect('accounts:login-user')

## view to register a user
def register(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.is_email_verified = False
            user.save()
            send_verification_email(user, request)
            messages.success(request, "Registration successful! Check your email to verify your account.")
            return redirect('accounts:login-user')
        else:
            print(form.errors)  # Debugging errors
    else:
        form = UserRegistrationForm()
    return render(request, 'accounts/register.html', {'form': form})
