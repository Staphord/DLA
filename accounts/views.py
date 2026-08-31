from django.conf import settings
from django.contrib.auth import login, authenticate, logout
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponseRedirect
from django.contrib import messages
from django.urls import reverse, reverse_lazy
from django.utils.crypto import get_random_string
from django.utils.http import url_has_allowed_host_and_scheme
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives, send_mail, get_connection
from django.contrib.auth.views import (
    PasswordResetView,
    PasswordResetDoneView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)
from django.contrib.auth.views import INTERNAL_RESET_SESSION_TOKEN
from django.views.generic import FormView

from accounts.forms import CustomPasswordResetForm
from accounts.models import CustomUser, Invitation, VerificationToken
from solicitations.forms import UserRegistrationForm


def _login_safe_next(request):
    candidate = request.POST.get('next') or request.GET.get('next')
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return ''


## view to log in a user
def login_user(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            # If the login was triggered by an auth-protected page,
            # Django passes `next`. Respect it so user stays on the
            # original page (e.g. /solicitations/user-profile/1/).
            next_url = request.POST.get('next') or request.GET.get('next')
            if next_url and url_has_allowed_host_and_scheme(
                next_url,
                allowed_hosts={request.get_host()},
                require_https=request.is_secure(),
            ):
                # Keep /DLA prefix when deployed under a subpath.
                script_prefix = getattr(settings, 'FORCE_SCRIPT_NAME', '') or ''
                script_prefix = script_prefix.rstrip('/')
                if script_prefix and next_url.startswith('/solicitations/') and not next_url.startswith(f"{script_prefix}/solicitations/"):
                    next_url = f"{script_prefix}{next_url}"
                if script_prefix and next_url.startswith('/admin/') and not next_url.startswith(f"{script_prefix}/admin/"):
                    next_url = f"{script_prefix}{next_url}"

                return redirect(next_url)

            # Fallback
            return redirect('solicitations:home')

        else:
            return render(
                request,
                'accounts/login.html',
                {
                    'login_error': True,
                    'username': request.POST.get('username', ''),
                    'next': _login_safe_next(request),
                },
            )

    return render(
        request,
        'accounts/login.html',
        {'next': _login_safe_next(request)},
    )

## view to log out a user
def logout_user(request):
    logout(request)
    return redirect('login-user')

def create_verification_token(user):
    token = get_random_string(64)
    VerificationToken.objects.create(user=user, token=token)
    return token

def send_verification_email(user, request):
    token = create_verification_token(user)  # Generate a unique token
    
    # Generate the full verification link
    verification_link = f"{settings.BASE_URL}{reverse('verify_email', args=[token])}"
    
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
    return redirect('login-user')

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
            return redirect('login-user')
        else:
            print(form.errors)  # Debugging errors
    else:
        form = UserRegistrationForm()
    return render(request, 'accounts/register.html', {'form': form})

def register_with_invitation(request, token):
    # Get invitation or return 404
    invitation = get_object_or_404(Invitation, token=token)
    
    # Check if invitation is valid
    if not invitation.is_valid:
        messages.error(request, 'This invitation link has expired or already been used.')
        return redirect('login-user')
    
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST)
        if form.is_valid():
            # Verify the email matches the invitation
            if form.cleaned_data['email'] != invitation.email:
                form.add_error('email', 'Please use the email address the invitation was sent to.')
            else:
                form.save()
                
                # Mark invitation as used
                invitation.used = True
                invitation.save()
                
                messages.success(request, 'Your account has been created! You can now log in.')
                return redirect('login-user')
    else:
        # Pre-fill the email field
        form = UserRegistrationForm(initial={'email': invitation.email})
    
    context = {
        'form': form,
        'invitation': invitation
    }
    return render(request, 'accounts/register_with_envitation.html', context)

class CustomPasswordResetView(PasswordResetView):
    template_name = 'accounts/password_reset_form.html'
    form_class = CustomPasswordResetForm
    success_url = reverse_lazy('password_reset_done')

class CustomPasswordResetDoneView(PasswordResetDoneView):
    template_name = 'accounts/password_reset_done.html'

class CustomPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = 'accounts/password_reset_confirm.html'
    success_url = reverse_lazy('password_reset_complete')

    def dispatch(self, request, *args, **kwargs):
        if 'uidb64' not in kwargs or 'token' not in kwargs:
            return super().dispatch(request, *args, **kwargs)

        self.validlink = False
        self.user = self.get_user(kwargs['uidb64'])
        token = kwargs['token']

        if self.user is not None:
            if token == self.reset_url_token:
                # URL has set-password: require session token (normal redirect flow)
                session_token = request.session.get(INTERNAL_RESET_SESSION_TOKEN)
                if self.token_generator.check_token(self.user, session_token):
                    self.validlink = True
                    return super().dispatch(request, *args, **kwargs)
            else:
                # URL has real token: show form directly so we don't rely on session
                if self.token_generator.check_token(self.user, token):
                    self.validlink = True
                    return FormView.dispatch(self, request, *args, **kwargs)

        # Invalid or expired link
        return self.render_to_response(self.get_context_data())

    def form_valid(self, form):
        user = form.save()
        self.request.session.pop(INTERNAL_RESET_SESSION_TOKEN, None)
        return super(FormView, self).form_valid(form)

class CustomPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = 'accounts/password_reset_complete.html'