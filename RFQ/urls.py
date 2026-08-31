from django.contrib import admin
from django.urls import path, include, reverse, reverse_lazy
from django.views.generic import RedirectView
from django.shortcuts import redirect
from django.conf import settings
from django.conf.urls.static import static
from RFQ.settings import MEDIA_ROOT

def _redirect_reset_confirm(request, uidb64, token):
    return redirect(reverse('password_reset_confirm', args=[uidb64, token]), permanent=False)

# Redirect solicitations auth URLs to accounts app so custom password-reset (and related) templates are used
solicitations_auth_redirects = [
    path('password_reset/', RedirectView.as_view(url=reverse_lazy('password_reset'), permanent=False)),
    path('password_reset/done/', RedirectView.as_view(url=reverse_lazy('password_reset_done'), permanent=False)),
    path('reset/<str:uidb64>/<str:token>/', _redirect_reset_confirm),
    path('reset/done/', RedirectView.as_view(url=reverse_lazy('password_reset_complete'), permanent=False)),
]

urlpatterns = [
    path('admin/', admin.site.urls),
    path('solicitations/', include('solicitations.urls')),
    path('', include('accounts.urls')),
    path('solicitations/', include(solicitations_auth_redirects)),
] + static(settings.MEDIA_URL, document_root=MEDIA_ROOT)

# Local runserver compatibility:
# with FORCE_SCRIPT_NAME=/DLA and WSGI path normalization, requests can reach
# resolver as /media/... instead of /DLA/media/...
_script_prefix = (getattr(settings, 'FORCE_SCRIPT_NAME', '') or '').rstrip('/')
if _script_prefix and settings.MEDIA_URL.startswith(f"{_script_prefix}/"):
    _media_url_without_prefix = settings.MEDIA_URL[len(_script_prefix):]
    urlpatterns += static(_media_url_without_prefix, document_root=MEDIA_ROOT)

admin.site.site_header = "SwiftnEasy RFQ Administration"
admin.site.site_title = "SwiftnEasy Admin Portal"
admin.site.index_title = "Welcome to SwiftnEasy Dashboard"