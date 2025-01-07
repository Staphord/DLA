from django.urls import path
from . import views

app_name = 'solicitations'

urlpatterns = [
    ################## HOMEPAGE URLS  ######################
    path('',views.home, name = 'home'),

    ###################  SOLICITATIONS URLS  ###############
    path('home/',views.solicitations, name = 'solicitations'),

    ###################  CLIENTS URLS  #####################
    path('clients/',views.clients, name = 'clients'),
    path('client-detail/<client>/', views.client_details, name='client-details'),
    path('new-client/', views.add_client, name='add-client'),

    ###################  RFQ URLS  #########################
    path('sent-rfqs/', views.sent_rfq, name='sent-rfq'),
    path('send-rfqs/', views.send_rfqs, name='send_rfqs'),
    path('search-sent-rfq/',views.search_sent_rfq, name='search-sent'),
    path('search-replied-rfq/',views.search_replied_rfq, name='search-replied'),
    path('rfq-detail/<rfq>/', views.rfq_detail, name='rfq-detail'),
    path('delete-rfq/<rfq>/', views.delete_rfq, name='delete-rfq'),
    path('myform/', views.rfq_reply_view, name='rfq_reply'),
    path('replied-rfqs/', views.replied_rfq, name='replied-rfq'),
    path('replied-rfq-detail/<rfq>/', views.replied_rfq_detail, name='replied-rfq-detail'),
    path('delete-replied-rfq/<rfq>/', views.delete_replied_rfq, name='delete-replied-rfq'),

    ####################  OEM URLS  ##########################
    path('active-oems/', views.active_oems, name='active-oems'),
    path('disabled-oems/', views.disabled_oems, name='disabled-oems'),
    path('oem-detail/<oem>', views.oem_detail, name = 'oem-detail'), 
    path('search-oem/',views.search_oem, name='search-oem'),
    path('disable-oem/', views.disable_oem, name='disable-oem'),
    path('enable-oem/<int:oem_id>/', views.enable_oem, name='enable-oem')

]
