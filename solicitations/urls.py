from django.urls import path
from . import views

app_name = 'solicitations'

urlpatterns = [
    path('',views.home, name = 'home'),
    path('home/',views.solicitations, name = 'solicitations'),
    path('clients/',views.clients, name = 'clients'),
    path('send-rfqs/', views.send_rfqs, name='send_rfqs'),
    path('client-detail/<client>/', views.client_details, name='client-details'),
    path('new-client/', views.add_client, name='add-client'),
    path('sent-rfqs/', views.sent_rfq, name='sent-rfq'),
    path('search-sent-rfq/',views.search_sent_rfq, name='search-sent'),
    path('search-replied-rfq/',views.search_replied_rfq, name='search-replied'),
    path('rfq-detail/<rfq>/', views.rfq_detail, name='rfq-detail'),
    path('delete-rfq/<rfq>/', views.delete_rfq, name='delete-rfq'),
    path('myform/', views.rfq_reply_view, name='rfq_reply'),
    path('replied-rfqs/', views.replied_rfq, name='replied-rfq'),
    path('replied-rfq-detail/<rfq>/', views.replied_rfq_detail, name='replied-rfq-detail'),
    path('delete-replied-rfq/<rfq>/', views.delete_replied_rfq, name='delete-replied-rfq'),
    path('all-oems/', views.all_oems, name='all-oems'),
    path('oem-detail/<oem>', views.oem_detail, name = 'oem-detail'), 
    path('search-oem/',views.search_oem, name='search-oem'),

]
