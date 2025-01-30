from django.contrib import admin
from django.urls import path,include
from django.conf import settings
from django.conf.urls.static import static
from RFQ.settings import MEDIA_ROOT

urlpatterns = [
    path('admin/', admin.site.urls),
    path('solicitations/', include('solicitations.urls')),
    path('',include('accounts.urls')),
    path('', include('django.contrib.auth.urls')),
]+ static(settings.MEDIA_URL, document_root = MEDIA_ROOT)
