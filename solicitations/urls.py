from django.urls import path
from . import views


app_name = 'solicitations'

urlpatterns = [
    ################## HOMEPAGE URLS  ######################
    path('home', views.home, name='home'),

    ###################  SOLICITATIONS URLS  ###############
    path('home/', views.solicitations, name='solicitations'),
    path('scrap-solicitations/', views.scrap_solicitations,
         name='scrap-solicitations'),
    path('solicitation-detail/<solicitation>/',
         views.solicitation_detail, name='solicitation-detail'),
    path('solicitations/clear/', views.clear_solicitations,
         name='clear_solicitations'),
    path('delete-solicitation/<solicitation>/',
         views.delete_solicitation, name='delete-solicitation'),
    path('searched-solicitations/', views.searched_solicitations,
         name='searched-solicitations'),
    path('flitered-solicitations/', views.filtered_solicitations,
         name='filtered-solicitations'),
    path('email-settings/', views.email_settings, name='email-settings'),
    path('rfq-auto-fetch-settings/', views.rfq_auto_fetch_settings, name='rfq-auto-fetch-settings'),
    path('check-user-profile/', views.check_user_profile,
         name='check_user_profile'),
    path('check-task-status/', views.check_task_status, name='check_task_status'),
    path('check-processing-status/', views.check_processing_status,
         name='check_processing_status'),
    path('check-rfq-task-status/', views.check_task_status,
         name='check_rfq_task_status'),
    path('check-solicitation-status/', views.check_solicitation_status,
         name='check_solicitation_status'),
    path('api/get-user-state/', views.get_user_state, name='get_user_state'),
    path('api/update-user-state/', views.update_user_state,
         name='update_user_state'),
    path('api/sync-processing-status/', views.sync_processing_status,
         name='sync_processing_status'),
    path('tasks/', views.user_tasks_list, name='user-tasks-list'),
    path('tasks/<str:session_id>/', views.task_details, name='task_details'),
    path('stop-processing/', views.stop_rfq_processing,
         name='stop_rfq_processing'),
    path('api/logs/<str:session_id>/recent/',
         views.get_recent_logs_api, name='recent_logs_api'),

    ###################  CLIENTS URLS  #####################
    path('clients/', views.clients, name='clients'),
    path('client-detail/<client>/', views.client_details, name='client-details'),
    path('new-client/', views.add_client, name='add-client'),
    path('delete-client/<client>/', views.delete_client, name='delete-client'),
    path('user-profile/<client>/', views.user_profile, name='user-profile'),
    path('email-config/<int:client_id>/',
         views.email_config_view, name='email_config'),
    path('export-config/', views.export_config, name='export-config'),

    ###################  RFQ URLS  #########################
    path('sent-rfqs/', views.sent_rfq, name='sent-rfq'),
    path('send-rfqs/', views.send_rfqs, name='send_rfqs'),
    path('search-sent-rfq/', views.search_sent_rfq, name='search-sent'),
    path('rfq-detail/<rfq>/', views.rfq_detail, name='rfq-detail'),
    path('delete-rfq/<rfq>/', views.delete_rfq, name='delete-rfq'),
    path('fetch-mail-preview/', views.fetch_mail_preview,
         name='fetch_mail_preview'),
    path('update_mail_preview/', views.update_mail_preview,
         name='update_mail_preview'),
    path('get-chart-data/', views.get_chart_data, name='get_chart_data'),
    path('get-oem-status-data/', views.get_oem_status_data,
         name='get_oem_status_data'),
    path('bulk-delete-reports/', views.bulk_delete_reports,
         name='bulk-delete-reports'),
    path('delete-single-report/', views.delete_single_report,
         name='delete-single-report'),
    path('bulk-delete-tasks/', views.bulk_delete_tasks, name='bulk-delete-tasks'),
    path('delete-single-task/', views.delete_single_task,
         name='delete-single-task'),

    ###################  RFQ REPLIES (EXTRACTED FROM EMAILS) URLS  #########################
    path('replied-rfqs/', views.replied_rfq, name='replied-rfq'),
    path('add-replied-rfq/', views.add_replied_rfq, name='add-replied-rfq'),
    path('export-replied-rfqs/', views.export_replied_rfqs, name='export-replied-rfqs'),
    path('export-single-rfq-reply/<int:rfq_id>/', views.export_single_rfq_reply, name='export-single-rfq-reply'),
    path('fetch-rfq-replies-by-date/', views.fetch_rfq_replies_by_date, name='fetch-rfq-replies-by-date'),
    path('search-replied-rfq/', views.search_replied, name='search-replied'),
    path('replied-rfq-detail/<rfq>/',
         views.replied_rfq_detail, name='replied-rfq-detail'),
    path('edit-replied-rfq/<rfq>/',
         views.edit_replied_rfq, name='edit-replied-rfq'),
    path('delete-replied-rfq/<rfq>/',
         views.delete_replied_rfq, name='delete-replied-rfq'),

    ####################  OEM URLS  ##########################
    path('active-oems/', views.active_oems, name='active-oems'),
    path('disabled-oems/', views.disabled_oems, name='disabled-oems'),
    path('oem-detail/<oem>', views.oem_detail, name='oem-detail'),
    path('search-oem/', views.search_oem, name='search-oem'),
    path('disable-oem/', views.disable_oem, name='disable-oem'),
    path('enable-oem/<int:oem>/', views.enable_oem, name='enable-oem'),
    path('oem/edit/<int:oem>/', views.edit_oem, name='edit-oem'),
    path('add-oem/', views.add_oem, name='add-oem'),
    path('import-oem/', views.import_oem, name='import-oem'),
    path('clear-duplicate-flag/', views.clear_duplicate_flag,
         name='clear-duplicate-flag'),
    path('clear-import-duplicate-flag/', views.clear_import_duplicate_flag,
         name='clear-import-duplicate-flag'),
    path('oem/<int:oem_id>/delete/', views.delete_oem, name='delete-oem'),
    path('oems/bulk-delete/', views.bulk_delete_oems, name='bulk-delete-oems'),
    path('search-disabled-oem/', views.search_disabled_oem,
         name='search-disabled-oem'),


    #################### CRON URLS  ##########################
    path("workflow/", views.update_github_workflow, name="workflow"),

    #################### Accounts url  #######################
    path('invite/', views.invite_user, name='invite_user'),
    path('check-time/', views.my_time_view),

    ###################   Task summary report ###############
    path('rfq/reports/', views.rfq_reports_view, name='rfq-reports'),

]
