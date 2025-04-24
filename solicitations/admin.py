from django.contrib import admin
from . models import Solicitation

# Register your models here.
admin.site.register(Solicitation)

admin.site.site_header = "Gilgal Tech Administration"
admin.site.site_title = "Gilgal Tech Administration"
admin.site.index_title = "Gilgal Tech Administrationd"