from django.urls import path
from . import views

app_name = 'solicitations'

urlpatterns = [
    ################## HOMEPAGE URLS  ######################
    path('base/', views.base, name='base'),
    path('',views.home, name = 'home'),

    ###################  SOLICITATIONS URLS  ###############
    path('home/',views.solicitations, name = 'solicitations'),
    path('scrap-solicitations/',views.scrap_solicitations, name = 'scrap-solicitations'),
    path('solicitation-detail/<solicitation>/', views.solicitation_detail, name='solicitation-detail'),
    path('solicitations/clear/', views.clear_solicitations, name='clear_solicitations'),
    path('delete-solicitation/<solicitation>/', views.delete_solicitation, name='delete-solicitation'),
    path('searched-solicitations/',views.searched_solicitations, name='searched-solicitations'),
    path('flitered-solicitations/', views.filtered_solicitations, name='filtered-solicitations'),
    path('email-settings/', views.email_settings, name='email-settings'),

    ###################  CLIENTS URLS  #####################
    path('clients/',views.clients, name = 'clients'),
    path('client-detail/<client>/', views.client_details, name='client-details'),
    path('new-client/', views.add_client, name='add-client'),
    path('delete-client/<client>/', views.delete_client, name='delete-client'),

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
    path('fetch-mail-preview/', views.fetch_mail_preview, name='fetch_mail_preview'),
    path('update_mail_preview/', views.update_mail_preview, name='update_mail_preview'),
    path('get-chart-data/', views.get_chart_data, name='get_chart_data'),
    path('get-oem-status-data/', views.get_oem_status_data, name='get_oem_status_data'),

    ####################  OEM URLS  ##########################
    path('active-oems/', views.active_oems, name='active-oems'),
    path('disabled-oems/', views.disabled_oems, name='disabled-oems'),
    path('oem-detail/<oem>', views.oem_detail, name = 'oem-detail'), 
    path('search-oem/',views.search_oem, name='search-oem'),
    path('disable-oem/', views.disable_oem, name='disable-oem'),
    path('enable-oem/<int:oem_id>/', views.enable_oem, name='enable-oem'),
    path('oem/edit/<int:oem>/', views.edit_oem, name='edit-oem'),

    #################### CRON URLS  ##########################
    path("workflow/", views.update_github_workflow, name="workflow"),

]
