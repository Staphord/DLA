import json
import os
from django.core.mail import send_mail,get_connection
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponseForbidden, HttpResponseNotFound, JsonResponse
from accounts.models import CustomUser, Invitation, VerificationToken
from . models import RFQ, EmailSettings,UserEmailConfig,RFQTaskSummary,UserSelectionState,RFQScriptLog, RFQScriptSession, MailTemplate, OEMUser, Solicitation,OEM,GitHubWorkflow,SolicitationEmailStatus, UserOEMCustomization
from django.contrib import messages
import subprocess
import threading
from django.utils.timezone import now
from . forms import EmailSettingsForm,EmailConfigForm, LogoUpdateForm,CustomPasswordChangeForm, UserOEMCustomizationForm, UserRegistrationForm,GitHubWorkflowForm,UserUpdateForm
from django.core.paginator import Paginator
from django.contrib.auth import update_session_auth_hash
from django.db.models import Q,Exists, OuterRef, Case, When, BooleanField,Prefetch,Value, IntegerField,Avg,Count,Sum
from django.template.loader import render_to_string
from datetime import datetime,timedelta,date
from django.utils import timezone
from .context_processors import rfq_processing_context
from git import Repo
from ruamel.yaml import YAML
from django.db.models import Sum
from django.core.signing import Signer
import base64
from accounts.views import register_with_invitation
from django.views.decorators.csrf import csrf_exempt 
from django.urls import reverse, NoReverseMatch
import pandas as pd
from django.db import transaction, DataError, IntegrityError
import traceback
import logging
from django.views.decorators.http import require_POST
from .tasks import process_large_manual_rfq_batch
from django.views.decorators.http import require_http_methods
from django_q.tasks import async_task
from django_q.tasks import Task
from django_q.models import OrmQ
import re
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth.decorators import login_required

logger = logging.getLogger('rfq')


## path to yaml file
WORKFLOW_FILE_PATH = "/home/gilgalrfq/DLA.github/workflows/extract_data.yml"

def home(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            request.session['selected_date'] = data.get('selected_date')
            request.session['is_user_input'] = data.get('is_user_input', False)
            return JsonResponse({'status': 'success'})
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON'})

    user = request.user
    today = now().date()
    cutoff_date = today - timedelta(days=14)

    # Subquery: Already sent emails
    sent_emails_subquery = SolicitationEmailStatus.objects.filter(
        user=user,
        email_sent=True,
        solicitation=OuterRef('pk')
    )

    # Subquery: Disabled OEMs
    disabled_oems_subquery = OEMUser.objects.filter(
        user=user,
        is_disabled=True,
        oem__cage=OuterRef('cage')
    )

    # USE THE SAME FILTERING LOGIC AS solicitations VIEW
    solicitations_qs = Solicitation.objects.exclude(
        Q(cage__in=['-', 'N/A', '']) |
        Q(organization_name__in=['N/A', '']) |
        Q(email__in=['n/a', '']) |
        Q(return_by_date__isnull=True) |
        Q(return_by_date='') |
        Q(email__contains='#') |
        Exists(sent_emails_subquery) |
        Exists(disabled_oems_subquery)
    ).filter(
        scraped_date__gte=cutoff_date
    ).extra(
        where=["return_by_date REGEXP '^[0-9]{1,2}-[0-9]{1,2}-[0-9]{4}$'"]
    )

    # COUNT DIRECTLY FROM THE QUERYSET (same as solicitations view)
    total_solicitations = solicitations_qs.count()

    # Clients
    clients = CustomUser.objects.exclude(is_superuser=True)\
        .filter(user_type='client')\
        .exclude(Q(first_name='') | Q(first_name=None) | Q(last_name='') | Q(last_name=None))
    total_clients = clients.count()

    # RFQs
    sent_rfqs = RFQ.objects.filter(created_by=user)
    total_sent_rfqs = sent_rfqs.count()

    # Selected date from session
    selected_date = request.session.get('selected_date', today.strftime("%m-%d-%Y"))

    context = {
        'total_clients': total_clients,
        'total_solicitations': total_solicitations,
        'sent_rfqs': sent_rfqs,
        'total_sent_rfqs': total_sent_rfqs,
        'selected_date': selected_date,
        'is_user_input': request.session.get('is_user_input', False), 
    }

    return render(request, 'solicitations/home.html', context)

## view to show all solicitations
def solicitations(request):
    today = timezone.now().date()
    cutoff_date = today - timedelta(days=14)
    
    # OPTIMIZATION 1: Use subquery for sent emails (database-level filtering)
    sent_emails_subquery = SolicitationEmailStatus.objects.filter(
        user=request.user,
        email_sent=True,
        solicitation=OuterRef('pk')
    )
    
    # OPTIMIZATION 2: CORRECTED - Only exclude explicitly disabled OEMs
    # Show all solicitations EXCEPT those where user has explicitly disabled the OEM
    disabled_oems_subquery = OEMUser.objects.filter(
        user=request.user,
        is_disabled=True,  # Only exclude explicitly disabled OEMs
        oem__cage=OuterRef('cage')
    )
    
    # OPTIMIZATION 3: Single query with all filtering and prefetching
    solicitations_qs = Solicitation.objects.select_related().prefetch_related(
        Prefetch(
            'solicitationemailstatus_set',
            queryset=SolicitationEmailStatus.objects.filter(user=request.user),
            to_attr='user_email_statuses'
        )
    ).exclude(
        Q(cage__in=['-', 'N/A', '']) |
        Q(organization_name__in=['N/A', '']) |
        Q(email__in=['n/a', '']) |
        Q(return_by_date__isnull=True) |
        Q(return_by_date='') |
        Q(email__contains='#') |
        Exists(sent_emails_subquery) |
        Exists(disabled_oems_subquery)  # CORRECTED: Only exclude explicitly disabled
    ).filter(
        scraped_date__gte=cutoff_date
    ).order_by('-id')
    
    # OPTIMIZATION 4: Use raw SQL for date validation (much faster)
    solicitations_qs = solicitations_qs.extra(
        where=["return_by_date REGEXP '^[0-9]{1,2}-[0-9]{1,2}-[0-9]{4}$'"]
    )
    
    # OPTIMIZATION 5: Get total count efficiently
    total_count = solicitations_qs.count()
    
    # NEW: Get ALL valid solicitation IDs for global select all (before pagination)
    # This gets ALL IDs that match the filter criteria, not just current page
    all_filtered_solicitation_ids = list(solicitations_qs.values_list('id', flat=True))
    
    # All filtered IDs are valid for selection (disabled ones are already excluded)
    all_valid_solicitation_ids = all_filtered_solicitation_ids
    
    # OPTIMIZATION 6: Paginate at database level
    page_size = 25
    page_number = request.GET.get('page', 1)
    try:
        page_number = int(page_number)
    except (ValueError, TypeError):
        page_number = 1
    
    # Calculate offset for manual pagination
    offset = (page_number - 1) * page_size
    limit = page_size
    
    # Get only the records for current page
    current_page_solicitations = list(solicitations_qs[offset:offset + limit])
    
    # OPTIMIZATION 7: Bulk process only current page data
    for solicitation in current_page_solicitations:
        # Email status from prefetched data
        solicitation.email_sent = (
            solicitation.user_email_statuses[0].email_sent 
            if solicitation.user_email_statuses else False
        )
        # Check if this specific OEM is disabled for this user
        try:
            oem_user = OEMUser.objects.get(user=request.user, oem__cage=solicitation.cage)
            solicitation.oem_disabled = oem_user.is_disabled
        except OEMUser.DoesNotExist:
            # No OEMUser record means not disabled (user hasn't interacted with this OEM)
            solicitation.oem_disabled = False
    
    # Create paginator manually
    from django.core.paginator import Page
    from math import ceil
    
    num_pages = ceil(total_count / page_size)
    page_obj = Page(current_page_solicitations, page_number, paginator=None)
    page_obj.paginator = type('obj', (object,), {
        'num_pages': num_pages,
        'count': total_count,
        'per_page': page_size,
        'page_range': range(1, num_pages + 1)
    })()
    page_obj.has_next = lambda: page_number < num_pages
    page_obj.has_previous = lambda: page_number > 1
    page_obj.next_page_number = lambda: page_number + 1 if page_obj.has_next() else None
    page_obj.previous_page_number = lambda: page_number - 1 if page_obj.has_previous() else None
    page_obj.start_index = lambda: offset + 1 if current_page_solicitations else 0
    page_obj.end_index = lambda: min(offset + len(current_page_solicitations), total_count)
    
    # OPTIMIZATION 9: Simple email settings query
    try:
        email_settings = EmailSettings.objects.only(
            'auto_send', 'send_day', 'send_time'
        ).get(user=request.user)
        auto_send = email_settings.auto_send
        day_choices_dict = dict(EmailSettings.DAY_CHOICES)
        send_day_display = day_choices_dict[email_settings.send_day]
        send_time_display = email_settings.send_time.strftime('%I:%M %p')
    except EmailSettings.DoesNotExist:
        auto_send = False
        send_day_display = "Every day"
        send_time_display = "09:00 AM"
        
    context = {
        'page_obj': page_obj,
        'solicitations': current_page_solicitations,  # Add for template compatibility
        'total_solicitations': total_count,
        'auto_send': auto_send,
        'send_day_display': send_day_display,
        'send_time_display': send_time_display,
        'cutoff_date': cutoff_date.strftime("%Y-%m-%d"),
        'all_valid_solicitation_ids': all_valid_solicitation_ids,  # ALL valid IDs across ALL pages
        'available_solicitations': len(all_valid_solicitation_ids),  # Total available across all pages
        'user': request.user,  
        'user_id': request.user.id,
    }
    
    return render(request, 'solicitations/solicitations.html', context)

def get_user_oem_data(user, oem):
    """
    Get OEM data for a specific user, prioritizing their customizations 
    """
    try:
        customization = UserOEMCustomization.objects.get(user=user, oem=oem)
        return {
            'name': customization.custom_name or oem.name,
            'email': customization.custom_email or oem.email,
            'phone': customization.custom_phone or oem.phone,
            'fax': customization.custom_fax or oem.fax,
            'city': customization.custom_city or oem.city,
            'street': customization.custom_street or oem.street,
            'postal_code': customization.custom_postal_code or oem.postal_code,
            'poc': customization.custom_poc or oem.poc,
            'cage': oem.cage,  # CAGE code should never be customized
            'has_customizations': True
        }
    except UserOEMCustomization.DoesNotExist:
        return {
            'name': oem.name,
            'email': oem.email,
            'phone': oem.phone,
            'fax': oem.fax,
            'city': oem.city,
            'street': oem.street,
            'postal_code': oem.postal_code,
            'poc': oem.poc,
            'cage': oem.cage,
            'has_customizations': False
        }

## view to show solicitation detail
def solicitation_detail(request,solicitation):
    solicitation_detail = Solicitation.objects.get(pk=solicitation)
    context = {"solicitation_detail":solicitation_detail}
    return render(request,'solicitations/solicitation-detail.html',context)

def clear_solicitations(request):
    if request.method == "POST":  
        mysolicitations = Solicitation.objects.all()
        mysolicitations.delete()
        messages.success(request, "All solicitations have been cleared successfully.")
        return redirect('solicitations:solicitations')

    messages.error(request, "Invalid request method.")
    return redirect('solicitations:solicitations')

def delete_solicitation(request,solicitation):
    solicitation = Solicitation.objects.get(pk = solicitation)
    solicitation.delete()
    return redirect('solicitations:solicitations')

@csrf_exempt 
def scrap_solicitations(request):
    if request.method == "POST" and request.headers.get("X-Requested-With") == "XMLHttpRequest":
        try:
            data = json.loads(request.body) if request.body else {}
            scrape_date = data.get('date')
            
            if scrape_date:
                formated_date = datetime.strptime(scrape_date, "%Y-%m-%d").strftime("%m-%d-%Y")
                logger.info(f"Scraping for date: {scrape_date}")
            else:
                formated_date = datetime.now().strftime("%m-%d-%Y")
                logger.info("No scrape date provided. Defaulting to current date.")
            
            python_exec = "/home/gilgalrfq/env/bin/python"
            script_path = "/home/gilgalrfq/DLA/extractSolicitations.py"
            
            result = subprocess.Popen(
                [python_exec, script_path, str(formated_date)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Log real-time output
            for line in iter(result.stdout.readline, ''):
                if line:
                    logger.debug(f"Script output: {line.strip()}")

            # Wait and capture final output
            stdout, stderr = result.communicate()

            if result.returncode != 0:
                error_message = f"Subprocess failed with error: {stderr.strip()}"
                logger.error(error_message)
                return JsonResponse({"success": False, "error": error_message})

            logger.info("Subprocess completed successfully.")
            return JsonResponse({"success": True})

        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {str(e)}")
            return JsonResponse({"success": False, "error": "Invalid JSON in request body"})

        except Exception as e:
            logger.exception("Unexpected error during solicitation scraping")
            return JsonResponse({"success": False, "error": str(e)})

    else:
        logger.warning("Invalid request method or missing AJAX header")
        return JsonResponse({"success": False, "error": "Invalid request method or headers"})
                        
def searched_solicitations(request):
    if request.method == "POST":
        mysearch = request.POST.get('mysearch', '') 
        if mysearch:
            today = timezone.now().date()
            cutoff_date = today - timedelta(days=7)
            
            # OPTIMIZATION 1: Use subqueries for database-level filtering (same as other views)
            sent_emails_subquery = SolicitationEmailStatus.objects.filter(
                user=request.user,
                email_sent=True,
                solicitation=OuterRef('pk')
            )
            
            # OPTIMIZATION 2: Only exclude explicitly disabled OEMs
            disabled_oems_subquery = OEMUser.objects.filter(
                user=request.user,
                is_disabled=True,
                oem__cage=OuterRef('cage')
            )
            
            # OPTIMIZATION 3: Use consistent filtering logic with other views
            solicitations_qs = Solicitation.objects.exclude(
                Q(cage__in=['-', 'N/A', '']) |
                Q(organization_name__in=['N/A', '']) |
                Q(email__in=['n/a', '']) |
                Q(return_by_date__isnull=True) |
                Q(return_by_date='') |
                Q(email__contains='#') |
                Exists(sent_emails_subquery) |
                Exists(disabled_oems_subquery)
            ).filter(
                scraped_date__gte=cutoff_date
            ).extra(
                # Filter valid dates at database level
                where=["return_by_date REGEXP '^[0-9]{1,2}-[0-9]{1,2}-[0-9]{4}$'"]
            ).filter(
                # Search filters
                Q(cage__icontains=mysearch) | 
                Q(NSN__icontains=mysearch) | 
                Q(solicitation__icontains=mysearch) | 
                Q(quantity__icontains=mysearch) | 
                Q(nomenclature__icontains=mysearch)
            ).order_by('-scraped_date')
            
            # Get ALL valid solicitation IDs for global select all (CRITICAL for select all functionality)
            all_valid_solicitation_ids = list(solicitations_qs.values_list('id', flat=True))
            
            # Get the actual solicitation objects for display
            data = list(solicitations_qs)
            
            # OPTIMIZATION 4: Process solicitations for template (same as other views)
            # Bulk fetch email statuses
            solicitation_ids = [s.id for s in data]
            email_statuses = {}
            if solicitation_ids:
                email_status_qs = SolicitationEmailStatus.objects.filter(
                    solicitation_id__in=solicitation_ids,
                    user=request.user
                )
                for es in email_status_qs:
                    email_statuses[es.solicitation_id] = es
            
            # Bulk fetch OEM data
            cage_codes = [s.cage for s in data]
            oem_dict = {oem.cage: oem for oem in OEM.objects.filter(cage__in=cage_codes)}
            
            # Process each solicitation
            for solicitation in data:
                # Check if OEM is disabled for this user
                try:
                    oem_user = OEMUser.objects.get(user=request.user, oem__cage=solicitation.cage)
                    solicitation.oem_disabled = oem_user.is_disabled
                except OEMUser.DoesNotExist:
                    solicitation.oem_disabled = False
                
                # Email status
                email_status = email_statuses.get(solicitation.id)
                solicitation.email_sent = email_status.email_sent if email_status else False
                
                # Add email status object for template
                solicitation.email_status = email_status or type('EmailStatus', (), {
                    'email_sent': False,
                    'email_sent_at': None
                })()
                        
            context = {
                'mysearch': mysearch, 
                'data': data,
                # CRITICAL: Add these for JavaScript functionality
                'all_valid_solicitation_ids': all_valid_solicitation_ids,
                'available_solicitations': len(all_valid_solicitation_ids),
                'total_solicitations': len(data),
                'cutoff_date': cutoff_date.strftime("%Y-%m-%d"),
                'user': request.user,  # Make sure user is available
            }
            return render(request, 'solicitations/searched_solicitations.html', context)
        else:
            # Empty search case
            context = {
                'mysearch': '', 
                'data': [],
                'all_valid_solicitation_ids': [],
                'available_solicitations': 0,
                'total_solicitations': 0,
                'user': request.user,
            }
            return render(request, 'solicitations/searched_solicitations.html', context)
    else:
        # GET request case
        context = {
            'mysearch': '', 
            'data': [],
            'all_valid_solicitation_ids': [],
            'available_solicitations': 0,
            'total_solicitations': 0,
            'user': request.user,
        }
        return render(request, 'solicitations/searched_solicitations.html', context)

def filtered_solicitations(request):
    try:
        today = timezone.now().date()
        cutoff_date = today - timedelta(days=7)
        
        # OPTIMIZATION 1: Use subqueries for database-level filtering
        sent_emails_subquery = SolicitationEmailStatus.objects.filter(
            user=request.user,
            email_sent=True,
            solicitation=OuterRef('pk')
        )
        
        # FIXED: Only exclude explicitly disabled OEMs (show all others by default)
        disabled_oems_subquery = OEMUser.objects.filter(
            user=request.user,
            is_disabled=True,  # Only exclude explicitly disabled OEMs
            oem__cage=OuterRef('cage')
        )
        
        # OPTIMIZATION 2: Start with base query using database filtering
        solicitations_qs = Solicitation.objects.exclude(
            Q(cage__in=['-', 'N/A', '']) |
            Q(organization_name__in=['N/A', '']) |
            Q(email__in=['n/a', '']) |
            Q(email__contains='#') |
            Exists(sent_emails_subquery) |
            Exists(disabled_oems_subquery)  # CORRECTED: Only exclude explicitly disabled
        ).filter(
            scraped_date__gte=cutoff_date
        ).extra(
            # OPTIMIZATION 3: Filter valid dates at database level
            where=["return_by_date REGEXP '^[0-9]{1,2}-[0-9]{1,2}-[0-9]{4}$'"]
        ).order_by('-scraped_date')
        
        # OPTIMIZATION 4: Handle date filtering more efficiently
        if request.method == 'POST':
            issued_date_from = request.POST.get('issued_date_from')
            issued_date_to = request.POST.get('issued_date_to')
            return_by_date_from = request.POST.get('return_by_date_from')
            return_by_date_to = request.POST.get('return_by_date_to')
            
            # Filter by issued date range (database level when possible)
            if issued_date_from and issued_date_to:
                try:
                    issued_from_date = datetime.strptime(issued_date_from, '%Y-%m-%d').date()
                    issued_to_date = datetime.strptime(issued_date_to, '%Y-%m-%d').date()
                    
                    # Use database-level date filtering with REGEX
                    issued_from_str = issued_from_date.strftime('%m-%d-%Y')
                    issued_to_str = issued_to_date.strftime('%m-%d-%Y')
                    
                    # Get valid solicitation IDs with date filtering
                    valid_issued_ids = []
                    
                    # OPTIMIZATION 5: Use values_list to get only IDs and dates
                    date_records = solicitations_qs.values_list('id', 'issued_date')
                    
                    for sol_id, issued_date in date_records:
                        if not issued_date:
                            continue
                        try:
                            sol_date = datetime.strptime(issued_date, '%m-%d-%Y').date()
                            if issued_from_date <= sol_date <= issued_to_date:
                                valid_issued_ids.append(sol_id)
                        except (ValueError, TypeError):
                            continue
                    
                    solicitations_qs = solicitations_qs.filter(id__in=valid_issued_ids)
                    
                except ValueError as e:
                    logger.error(f"Invalid issued date format: {e}")
            
            # Filter by return by date range
            if return_by_date_from and return_by_date_to:
                try:
                    return_from_date = datetime.strptime(return_by_date_from, '%Y-%m-%d').date()
                    return_to_date = datetime.strptime(return_by_date_to, '%Y-%m-%d').date()
                    
                    valid_return_ids = []
                    
                    # OPTIMIZATION 6: Use values_list for return dates too
                    date_records = solicitations_qs.values_list('id', 'return_by_date')
                    
                    for sol_id, return_date in date_records:
                        if not return_date:
                            continue
                        try:
                            sol_date = datetime.strptime(return_date, '%m-%d-%Y').date()
                            if return_from_date <= sol_date <= return_to_date:
                                valid_return_ids.append(sol_id)
                        except (ValueError, TypeError):
                            continue
                    
                    solicitations_qs = solicitations_qs.filter(id__in=valid_return_ids)
                    
                except ValueError as e:
                    logger.error(f"Invalid return by date format: {e}")
        
        # OPTIMIZATION 7: Get total count before pagination
        total_count = solicitations_qs.count()
        
        # NEW: Get ALL valid solicitation IDs for global select all (before pagination)
        # This gets ALL IDs that match the filter criteria, not just current page
        all_filtered_solicitation_ids = list(solicitations_qs.values_list('id', flat=True))
        
        # SIMPLIFIED: Since disabled OEMs are already excluded by the query,
        # and sent emails are already excluded, all filtered IDs are valid
        all_valid_solicitation_ids = all_filtered_solicitation_ids
        
        # OPTIMIZATION 8: Add pagination to avoid loading all records for display
        page_size = 20
        paginator = Paginator(solicitations_qs, page_size)
        page_number = request.GET.get('page', 1)
        page_obj = paginator.get_page(page_number)
        
        # OPTIMIZATION 9: Process only current page items
        current_page_solicitations = list(page_obj)
        
        # OPTIMIZATION 10: Bulk fetch email statuses for current page only
        solicitation_ids = [s.id for s in current_page_solicitations]
        email_statuses = {}
        if solicitation_ids:
            email_status_qs = SolicitationEmailStatus.objects.filter(
                solicitation_id__in=solicitation_ids,
                user=request.user
            )
            for es in email_status_qs:
                email_statuses[es.solicitation_id] = es
        
        # OPTIMIZATION 11: Bulk fetch OEM data for current page
        cage_codes = [s.cage for s in current_page_solicitations]
        oem_dict = {oem.cage: oem for oem in OEM.objects.filter(cage__in=cage_codes)}
        
        # Get disabled OEMs for current user (current page) - for display purposes only
        disabled_oem_cages = set(OEMUser.objects.filter(
            user=request.user,
            is_disabled=True,
            oem__cage__in=cage_codes
        ).values_list('oem__cage', flat=True))
        
        # Process current page solicitations
        for solicitation in current_page_solicitations:
            # Check if this specific OEM is disabled for this user (for template display)
            try:
                oem_user = OEMUser.objects.get(user=request.user, oem__cage=solicitation.cage)
                solicitation.oem_disabled = oem_user.is_disabled
            except OEMUser.DoesNotExist:
                # No OEMUser record means not disabled (user hasn't interacted with this OEM)
                solicitation.oem_disabled = False
            
            # Email status
            email_status = email_statuses.get(solicitation.id)
            solicitation.email_sent = email_status.email_sent if email_status else False
            
            # Add email status object for template
            solicitation.email_status = email_status or type('EmailStatus', (), {
                'email_sent': False,
                'email_sent_at': None
            })()
                
        context = {
            'page_obj': page_obj,  # Changed from 'solicitations' to 'page_obj'
            'solicitations': current_page_solicitations,  # Keep for backward compatibility
            'all_valid_solicitation_ids': all_valid_solicitation_ids,  # ALL valid IDs across ALL pages
            'total_solicitations': total_count,
            'available_solicitations': len(all_valid_solicitation_ids),  # Total available across all pages
            'cutoff_date': cutoff_date.strftime("%Y-%m-%d"),
            # Filter values
            'issued_date_from': request.POST.get('issued_date_from', '') if request.method == 'POST' else '',
            'issued_date_to': request.POST.get('issued_date_to', '') if request.method == 'POST' else '',
            'return_by_date_from': request.POST.get('return_by_date_from', '') if request.method == 'POST' else '',
            'return_by_date_to': request.POST.get('return_by_date_to', '') if request.method == 'POST' else '',
        }
        
        return render(request, 'solicitations/filtered_solicitations.html', context)
        
    except Exception as e:
        logger.error(f"Error in filtered_solicitations for user {request.user.username}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        
        return render(request, 'solicitations/filtered_solicitations.html', {
            'page_obj': None,
            'solicitations': [],
            'all_valid_solicitation_ids': [],
            'error': 'An error occurred while filtering solicitations. Please try again.',
            'total_solicitations': 0,
            'available_solicitations': 0,
        })

def email_settings(request):
    """View for managing email automation settings"""
    # Get or create settings for the current user
    settings, created = EmailSettings.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        # Process the form data
        form = EmailSettingsForm(request.POST, instance=settings)
        
        # Check which action was performed
        action_type = request.POST.get('action_type', 'toggle_status')
        
        if form.is_valid():
            if action_type == 'save_schedule':
                # Save the schedule changes with the current auto_send value
                settings = form.save(commit=False)
                # Keep the current auto_send value (don't change it when saving schedule)
                settings.save()
                
                # Include schedule details in message
                day_display = dict(EmailSettings.DAY_CHOICES)[settings.send_day]
                scope_display = dict(EmailSettings.SCOPE_CHOICES)[settings.send_scope]
                
                # Get enabled times
                enabled_times = []
                if settings.enable_time_1:
                    enabled_times.append(settings.send_time_1.strftime('%I:%M %p'))
                if settings.enable_time_2:
                    enabled_times.append(settings.send_time_2.strftime('%I:%M %p'))
                if settings.enable_time_3:
                    enabled_times.append(settings.send_time_3.strftime('%I:%M %p'))
                
                times_str = ', '.join(enabled_times) if enabled_times else 'No times enabled'
                messages.success(request, f"Schedule updated and automation enabled ({day_display} at {times_str}, {scope_display.lower()})")
            
            elif action_type == 'toggle_status':
                # Toggle the auto_send status (opposite of current)
                old_status = settings.auto_send
                settings.auto_send = not settings.auto_send
                settings.save()
                
                # Create appropriate message
                status_msg = "enabled" if settings.auto_send else "disabled"
                
                if settings.auto_send:
                    # Include schedule details in message only when enabling
                    day_display = dict(EmailSettings.DAY_CHOICES)[settings.send_day]
                    scope_display = dict(EmailSettings.SCOPE_CHOICES)[settings.send_scope]
                    
                    # Get enabled times
                    enabled_times = []
                    if settings.enable_time_1:
                        enabled_times.append(settings.send_time_1.strftime('%I:%M %p'))
                    if settings.enable_time_2:
                        enabled_times.append(settings.send_time_2.strftime('%I:%M %p'))
                    if settings.enable_time_3:
                        enabled_times.append(settings.send_time_3.strftime('%I:%M %p'))
                    
                    times_str = ', '.join(enabled_times) if enabled_times else 'No times enabled'
                    schedule_info = f" ({day_display} at {times_str}, {scope_display.lower()})"
                    messages.success(request, f"Email automation has been {status_msg}{schedule_info}")
                else:
                    messages.success(request, f"Email automation has been {status_msg}")
            
            return redirect('solicitations:email-settings')
    else:
        form = EmailSettingsForm(instance=settings)
    
    context = {
        'form': form,
        'is_enabled': settings.auto_send,
        'current_auto_send': settings.auto_send,
    }
    
    return render(request, 'solicitations/email_settings.html', context)
#######################  CLIENT RELATED VIEWS  #########################
## view to show all clients
def clients(request):
    # Get all clients who are not superusers and have non-empty first_name AND last_name
    clients = CustomUser.objects.exclude(is_superuser=True)\
                               .filter(user_type='client')\
                               .exclude(Q(first_name='') | Q(first_name=None) | Q(last_name='') | Q(last_name=None))
    
    total_clients = clients.count()
        
    context = {
        "clients": clients,
        'total_clients': total_clients,
    }
    
    return render(request, 'solicitations/clients/clients.html', context)

## view add clients
def add_client(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                user = form.save(commit=False)
                user.set_password(form.cleaned_data['password1'])
                user.save()

                # Prepare email template context
                context = {
                    'first_name': user.first_name,
                    'username': user.username,
                    'password': form.cleaned_data['password1'],
                    'login_url': request.build_absolute_uri('/'),
                    'current_year': datetime.now().year,
                }

                # Render email content
                email_body = render_to_string('solicitations/invitation_email.html', context)

                # Send email
                send_mail(
                    subject="Welcome to Our Platform",
                    message="This is a fallback plain text version of the email.",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    fail_silently=False,
                    html_message=email_body,  
                )
                return redirect('solicitations:clients')
            except Exception as e:
                print(f"Error saving user: {e}")
        else:
            print(form.errors)
    else:
        form = UserRegistrationForm()

    return render(request, 'solicitations/clients/add.html', {'form': form})


# view to show client detail
def client_details(request, client):
    client = get_object_or_404(CustomUser, pk=client)

    if request.method == "POST":
        # Handle logo update form
        if 'logo_update' in request.POST:
            form = LogoUpdateForm(request.POST, request.FILES, instance=client)
            if form.is_valid():
                form.save()
                messages.success(request, "Logo updated successfully!")
                return redirect('solicitations:client-details', client=client.pk)
        

    form = LogoUpdateForm(instance=client)
    context = {
        'client': client,
        'form': form
    }
    return render(request, 'solicitations/clients/details.html', context)

def delete_client(request,client):
    clientToDelete = CustomUser.objects.get(pk=client)
    clientToDelete.delete()
    return redirect('solicitations:clients')

####################### RFQS RELATED VIEWS  ############################
## view to show all sent rfqs
def sent_rfq(request):
    sent_rfqs = RFQ.objects.filter(created_by=request.user) 
    # count all rfqs
    total_sent_rfqs = sent_rfqs.filter(created_by=request.user).count()
    p = Paginator(RFQ.objects.filter(created_by=request.user).order_by('-id'),25)
    page = request.GET.get('page')
    rfq = p.get_page(page)

    # Count all RFQs (total number of replies)
    context = {'sent_rfqs':sent_rfqs,'total_sent_rfqs':total_sent_rfqs,'rfq':rfq,
               }
    return render(request,'solicitations/procurements/sent_rfq.html',context)


#view to search for sent RFQS
def search_sent_rfq(request):
    if request.method == "POST":
        searched = request.POST['search-sent']
        
        # Enhanced search across multiple fields
        rfqId = RFQ.objects.filter(
            Q(created_by=request.user) & (
                Q(unique_id__icontains=searched) |  # Original search by RFQ ID
                Q(solicitation__part_number__icontains=searched) |  # Search by part number
                Q(solicitation__NSN__icontains=searched) |  # Search by NSN
                Q(solicitation__nomenclature__icontains=searched) |  # Search by nomenclature
                Q(solicitation__cage__icontains=searched) |  # Search by CAGE code
                Q(oem__name__icontains=searched)  # Search by OEM name
            )
        ).select_related('solicitation', 'oem')  # Optimize database queries
        
        # Get total sent RFQs for this user
        sent_rfqs = RFQ.objects.filter(created_by=request.user)
        total_sent_rfqs = sent_rfqs.count()
        
        context = {
            'searched': searched,
            'rfqId': rfqId,
            'total_sent_rfqs': total_sent_rfqs,
            'search_count': rfqId.count()  # Number of search results
        }
        return render(request, 'solicitations/procurements/searched_sent.html', context)
    else:
        return render(request, 'solicitations/procurements/sent_rfq.html')

## View to show RFQ detail
def rfq_detail(request, rfq):
    try:
        rfq = RFQ.objects.get(pk=rfq)
    except RFQ.DoesNotExist:
        return HttpResponseNotFound("RFQ not found")
        
    context = {
        'rfq': rfq,
    }
    
    return render(request, 'solicitations/procurements/rfq_detail.html', context)
 
##view to delete RFQ
def delete_rfq(request,rfq):
    delete_rfq = RFQ.objects.get(pk=rfq)
    delete_rfq.delete()
    return redirect('solicitations:sent-rfq')

## view to send RFQS
def send_rfqs(request):
    """
    Updated send_rfqs view to use email_sent boolean field
    """
    try:
        data = json.loads(request.body)
        selected_ids = data.get("selected_ids", [])
        
        if not selected_ids:
            return JsonResponse({"error": "No solicitations selected"}, status=400)
        
        user_id = request.user.id
        logger.info(f"=== MANUAL SEND_RFQS CALLED FOR {len(selected_ids)} RFQs by user {user_id} ({request.user.username}) ===")
        
        # CHECK: Verify solicitations exist and haven't been sent
        available_solicitations = Solicitation.objects.filter(
            id__in=selected_ids
        )        
        available_count = available_solicitations.count()
        if available_count == 0:
            return JsonResponse({"error": "No available solicitations found (may already be sent)"}, status=404)
        
        logger.info(f"Found {available_count} available solicitations")
        
        # Process the solicitations...
        from django_q.tasks import async_task
        from django.utils import timezone
        import hashlib
        
        # Create unique signature for this request
        sorted_ids = sorted(selected_ids)
        request_signature = hashlib.md5(f"{user_id}:{','.join(map(str, sorted_ids))}".encode()).hexdigest()
        
        timestamp = timezone.now().strftime("%H%M%S")
        task_name = f'MANUAL_RFQ_U{user_id}_{request_signature[:8]}_{len(selected_ids)}items_{timestamp}'
        
        if len(selected_ids) > 100:
            # Large batch processing
            from .tasks import process_large_manual_rfq_batch
            
            result = process_large_manual_rfq_batch(
                selected_ids=selected_ids,
                user_id=user_id,
                batch_size=15000
            )
            
            if result["status"] == "queued":
                return JsonResponse({
                    "message": f"Large batch of {len(selected_ids)} RFQs queued for background processing in {result['total_batches']} batches.",
                    "status": "queued",
                    "total_batches": result["total_batches"],
                    "total_rfqs": len(selected_ids),
                    "batch_size": result["batch_size"],
                    "estimated_completion_hours": max(1, result["total_batches"] * 0.5),
                    "processing_type": "manual_large",
                    "user_id": user_id,
                    "signature": request_signature[:8],
                }, status=202)
            else:
                return JsonResponse({"error": result.get("error", "Failed to queue tasks")}, status=500)
        
        else:
            # Standard batch processing
            task_id = async_task(
                'solicitations.tasks.process_manual_rfq_batch',
                selected_ids,
                user_id,
                None,  # mail_data will be fetched in task
                None,  # user_data will be fetched in task
                task_name=task_name,
                timeout=3600,  # 1 hour timeout
            )
            
            logger.info(f"Queued manual task {task_id} with signature {request_signature[:8]} for user {user_id}")
            
            return JsonResponse({
                "message": f"Processing {len(selected_ids)} RFQs in background.",
                "status": "processing",
                "task_id": task_id,
                "task_name": task_name,
                "signature": request_signature[:8],
                "estimated_completion_minutes": max(30, len(selected_ids) // 10),
                "processing_type": "manual_standard",
                "user_id": user_id,
            }, status=202)
    
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON data"}, status=400)
    except Exception as e:
        logger.error(f"Error in manual send_rfqs for user {user_id}: {e}")
        return JsonResponse({"error": str(e)}, status=500)

def get_chart_data(request):
    # Get current date for comparing return dates
    current_date = timezone.now().date()
    
    # First filter out solicitations with empty/dash cage codes
    all_valid_solicitations = Solicitation.objects.filter(
        ~Q(cage='') & ~Q(cage='-')  # Exclude empty or dash cage codes
    )
    
    valid_solicitations = []
    for sol in all_valid_solicitations:
        try:
            return_date = datetime.strptime(sol.return_by_date, "%m-%d-%Y").date()
            
            # Compare date objects (not strings)
            if return_date >= current_date:  # Only count if not expired
                valid_solicitations.append(sol.id)
        except (ValueError, TypeError):
            # Skip invalid dates
            pass
    
    # Count only valid solicitations
    solicitations = len(valid_solicitations)
        
    # Dynamic calculation for "Sent" - count of all RFQs
    sent = RFQ.objects.filter(created_by=request.user).count()
    
    # Return the data as JSON
    return JsonResponse({
        'solicitations': solicitations,
        'sent': sent
    })


def get_oem_status_data(request):
    # Count the number of active and disabled OEM users
    active_count = OEMUser.objects.filter(user=request.user, is_disabled=False).count()
    disabled_count = OEMUser.objects.filter(user=request.user, is_disabled=True).count()

    # Return the data as a JSON response
    return JsonResponse({
        'active': active_count,
        'disabled': disabled_count
    })

def fetch_mail_preview(request):
    if request.method == 'POST':
        try:
            # Parse the POST data to get selected IDs
            data = json.loads(request.body)
            selected_ids = data.get('selected_ids', [])
            
            logger.info(f"User {request.user.username} requesting preview for IDs: {selected_ids}")
            
            if not selected_ids:
                return JsonResponse({'error': 'No solicitations selected'}, status=400)
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error for user {request.user.username}: {e}")
            selected_ids = []
    
    user = request.user
    
    # Get mail template
    try:
        mail_template = MailTemplate.objects.filter(userMail=user).first()
    except Exception as e:
        logger.error(f"Error fetching mail template for user {user.username}: {e}")
        mail_template = None
    
    # Safeguard for optional fields in CustomUser
    company_name = getattr(user, 'companyName', "Your Company Name")
    address = getattr(user, 'address', "Your Address")
    logo_url = user.logo.url if hasattr(user, 'logo') and user.logo else None
    phone = getattr(user, 'phone', "Not Provided")
    email = getattr(user, 'email', "your email")
    personal_email = getattr(user, 'personal_email', "your personal email")
    fax = getattr(user, 'fax', "your fax")
    cage = getattr(user, 'cage', "your cage")
    website = getattr(user, 'website', "your website")
    first_name = getattr(user, 'first_name', "first name")
    last_name = getattr(user, 'last_name', "last name")
    title = getattr(user, 'title', "title") 
    
    # Prepare the base response data
    data = {
        "salutation": mail_template.salutation if mail_template else "Dear Mr/Ms",
        "heading": mail_template.heading if mail_template else "REQUEST FOR QUOTATION",
        "body": mail_template.body if mail_template else "I hope this message finds you well. We are currently looking for the following item. Kindly provide your lowest possible price.",
        'company': company_name,
        'address': address,
        'logo': logo_url,
        "phone": phone,
        "cage": cage,
        "fax": fax,
        "email": email,
        "personal_email": personal_email,
        "website": website,
        "first_name": first_name,
        "last_name": last_name,
        "title": title,
    }
    
    # Add dynamic solicitation data if selected_ids are provided
    if selected_ids:
        try:
            # Get the first selected solicitation as sample
            first_solicitation_id = selected_ids[0]
            logger.info(f"Fetching solicitation {first_solicitation_id} for user {user.username}")
            
            sample_solicitation = get_object_or_404(Solicitation, id=first_solicitation_id)
            
            logger.info(f"Found solicitation: {sample_solicitation.cage} - {sample_solicitation.nomenclature}")
            
            # Generate reference number and dates
            current_date = timezone.now().strftime('%m/%d/%Y')
            # Calculate reply deadline (3 days from today)
            reply_deadline = (timezone.now() + timezone.timedelta(days=3)).strftime('%m/%d/%Y')
            
            company_initial = getattr(user, 'company_initial', None) or (user.companyName[:3].upper() if user.companyName else 'GTS')
            reference_number = f"{company_initial}-DLA-{timezone.now().strftime('%m%d%y')}-{sample_solicitation.cage}-{str(sample_solicitation.id).zfill(6)}"
            
            # Get user-specific OEM data instead of solicitation's generic data
            try:
                oem = OEM.objects.get(cage=sample_solicitation.cage)
                user_oem_data = get_user_oem_data(user, oem)
                
                sample_oem = {
                    'organization_name': user_oem_data['name'],
                    'phone': user_oem_data['phone'],
                    'fax': user_oem_data['fax'],
                    'email': user_oem_data['email'],
                    'street_name': user_oem_data['street'],
                    'city': user_oem_data['city'],
                    'postal_code': user_oem_data['postal_code'],
                    'poc': user_oem_data['poc'],
                }
            except OEM.DoesNotExist:
                # Fallback to solicitation data if OEM not found
                sample_oem = {
                    'organization_name': sample_solicitation.organization_name or f'OEM Company for {sample_solicitation.cage}',
                    'phone': sample_solicitation.phone or '-',
                    'fax': sample_solicitation.fax or '-',
                    'email': sample_solicitation.email or '-',
                    'street_name': sample_solicitation.street_name or '-',
                    'city': sample_solicitation.city or '-',
                    'postal_code': sample_solicitation.postal_code or '-',
                }
            
            # Add sample solicitation data to response
            data.update({
                'sample_solicitation': {
                    'id': sample_solicitation.id,
                    'cage': sample_solicitation.cage,
                    'nomenclature': sample_solicitation.nomenclature,
                    'NSN': sample_solicitation.NSN,
                    'part_number': sample_solicitation.part_number or '-',
                    'unit': sample_solicitation.unit,
                    'quantity': sample_solicitation.quantity,
                    'return_by_date': sample_solicitation.return_by_date,
                    'inspection_point': sample_solicitation.inspection_point or '-',
                    'acceptance_point': sample_solicitation.acceptance_point or '-',
                    'deliver_fob': sample_solicitation.deliver_fob or '-',
                    'deliver_days': sample_solicitation.deliver_days or '-', 
                },
                
                # Use user-specific OEM data
                'sample_oem': sample_oem,
                
                'current_date': current_date,
                'reference_number': reference_number,
                'reply_deadline': reply_deadline,
            })
            
            logger.info(f"Successfully prepared dynamic data with user-specific OEM info for user {user.username}")
            
        except Solicitation.DoesNotExist:
            logger.error(f"Solicitation {first_solicitation_id} not found")
            return JsonResponse({'error': 'Selected solicitation not found'}, status=404)
        except Exception as e:
            logger.error(f"Error processing dynamic data for user {user.username}: {e}")
            # Continue without sample data - will show default values
    
    return JsonResponse(data)

def update_mail_preview(request):
    if request.method == 'POST':
        try:
            user = request.user
            print("User:", user)
            data = json.loads(request.body)
            print("Data received:", data)

            mail_template, created = MailTemplate.objects.get_or_create(userMail=user)
            print("MailTemplate created?", created)

            mail_template.heading = data.get('heading', mail_template.heading)
            mail_template.salutation = data.get('salutation', mail_template.salutation)
            mail_template.body = data.get('body', mail_template.body)
            mail_template.save()

            return JsonResponse({"message": "Mail template updated successfully!"}, status=200)
        except Exception as e:
            print("Error:", e)
            return JsonResponse({"error": str(e)}, status=400)
    return JsonResponse({"error": "Invalid request method"}, status=405)

##########################  OEM RELATED VIEWS  ###############################
## view to show all active oems
def active_oems(request):
    user = request.user

    # Prefetch OEMUser and UserOEMCustomization related to the current user
    user_oem_qs = OEMUser.objects.filter(user=user, is_disabled=False)
    user_custom_qs = UserOEMCustomization.objects.filter(user=user)

    oem_qs = OEM.objects.filter(
        oemuser__in=user_oem_qs
    ).annotate(
        priority=Case(
            When(data_source__in=['manual', 'import'], then=Value(0)),
            default=Value(1),
            output_field=IntegerField()
        )
    ).prefetch_related(
        Prefetch('oemuser_set', queryset=user_oem_qs, to_attr='user_oem_entries'),
        Prefetch('useroemcustomization_set', queryset=user_custom_qs, to_attr='customizations')
    ).order_by('priority', '-created_at').distinct()

    oems_with_custom_data = []
    for oem in oem_qs:
        # Get related customization (if any)
        custom = oem.customizations[0] if oem.customizations else None

        oem.display_name = custom.custom_name if custom and custom.custom_name else oem.name
        oem.display_email = custom.custom_email if custom and custom.custom_email else oem.email
        oem.display_phone = custom.custom_phone if custom and custom.custom_phone else oem.phone
        oem.display_city = custom.custom_city if custom and custom.custom_city else oem.city
        oem.has_customizations = custom is not None
        oems_with_custom_data.append(oem)

    # Paginate
    paginator = Paginator(oems_with_custom_data, 50)
    page = request.GET.get('page')
    oem_page = paginator.get_page(page)

    # Disabled OEMs
    disabled_oems = OEM.objects.filter(oemuser__user=user, oemuser__is_disabled=True)

    context = {
        'oems': oems_with_custom_data,
        'oem': oem_page,
        'total_oems': len(oems_with_custom_data),
        'disabled_oems': disabled_oems,
    }
    return render(request, 'solicitations/oems/active_oems.html', context)

## view to show oem detail page
def oem_detail(request, oem):
    # Fetch the specific OEM object using the primary key
    oem_obj = get_object_or_404(OEM, pk=oem)
    
    # Check if user has access to this OEM (including disabled ones)
    user_oem = OEMUser.objects.filter(user=request.user, oem=oem_obj).first()
    if not user_oem:
        return HttpResponseForbidden("You do not have access to this OEM.")
    
    # Check if the OEM is disabled for this user
    is_disabled = user_oem.is_disabled
    
    # Get all OEMUser associations for this OEM
    oem_users = OEMUser.objects.filter(oem=oem_obj)
        
    # Get the user's customization for this OEM if it exists
    user_data = get_user_oem_data(request.user, oem_obj)
    
    # Pass the data to the template
    context = {
        'oem': oem_obj, 
        'oem_data': user_data,
        'oem_users': oem_users,
        'is_disabled': is_disabled,  
        'user_oem': user_oem,  
    }
    
    return render(request, 'solicitations/oems/oem_detail.html', context)

## view to search for OEM
def search_oem(request):
    if request.method == "POST":
        searched = request.POST['search-oem']
        
        # Get user's OEMs that match the search
        user_oems = OEM.objects.filter(
            oemuser__user=request.user,
            cage__icontains=searched
        )
        
        # Add user-specific data to each OEM
        oems_with_custom_data = []
        for oem in user_oems:
            user_data = get_user_oem_data(request.user, oem)
            oem.display_name = user_data['name']
            oem.display_email = user_data['email']
            oem.display_phone = user_data['phone']
            oem.display_city = user_data['city']
            oem.has_customizations = user_data['has_customizations']
            oems_with_custom_data.append(oem)        
        context = {
            'searched': searched,
            'oem': oems_with_custom_data,
        }
        return render(request, 'solicitations/oems/searched_oem.html', context)
    else:
        return render(request, 'solicitations/oems/active_oems.html')

@require_http_methods(["POST"])
def search_disabled_oem(request):
    """
    Search view for disabled OEMs by cage code or name
    (Following your existing search pattern)
    """
    if request.method == "POST":
        searched = request.POST['search-oem']
        
        # Get user's disabled OEMs that match the search with optimized query
        disabled_oem_users = OEMUser.objects.filter(
            Q(user=request.user) & Q(is_disabled=True)
        ).filter(
            Q(oem__cage__icontains=searched) |
            Q(oem__name__icontains=searched)
        ).select_related('oem').order_by('oem__cage')
        
        # Add user-specific data to each disabled OEM 
        disabled_oems_with_custom_data = []
        for disabled_oem_user in disabled_oem_users:
            user_data = get_user_oem_data(request.user, disabled_oem_user.oem)
            disabled_oem_user.display_name = user_data['name']
            disabled_oem_user.display_email = user_data['email']
            disabled_oem_user.display_phone = user_data['phone']
            disabled_oem_user.display_city = user_data['city']
            disabled_oem_user.has_customizations = user_data['has_customizations']
            disabled_oems_with_custom_data.append(disabled_oem_user)

        # Pagination for search results
        p = Paginator(disabled_oems_with_custom_data, 50)
        page = request.GET.get('page')
        disabled = p.get_page(page)
        
        # Add search feedback messages
        search_count = len(disabled_oems_with_custom_data)
        if search_count == 0:
            messages.info(request, f"No disabled OEMs found for '{searched}'.")
        else:
            messages.success(request, f"Found {search_count} disabled OEM(s) matching '{searched}'.")
        
        context = {
            'searched': searched,
            'disabled_oems': disabled_oems_with_custom_data,
            'disabled': disabled,
            'search_count': search_count,
            'is_search': True,
            'disabled_oem_users': disabled_oem_users  # For the count badge
        }
        return render(request, 'solicitations/oems/disabled_oems.html', context)
    else:
        return render(request, 'solicitations/oems/disabled_oems.html')
    
## view to show all disabled oems
def disabled_oems(request):
    user = request.user

    # Get user's active OEMs for display purposes
    active_oems = OEM.objects.filter(oemuser__user=user, oemuser__is_disabled=False)

    # Prefetch OEMUser (disabled only) and any customizations
    disabled_oem_users = OEMUser.objects.filter(user=user, is_disabled=True).select_related('oem')
    customizations_qs = UserOEMCustomization.objects.filter(user=user)

    # Create a dict of customizations keyed by (user_id, oem_id)
    custom_map = {
        (c.user_id, c.oem_id): c
        for c in customizations_qs
    }

    # Attach display data to each disabled OEMUser
    disabled_oems_with_custom_data = []
    for oem_user in disabled_oem_users:
        oem = oem_user.oem
        custom = custom_map.get((user.id, oem.id), None)

        oem_user.display_name = custom.custom_name if custom and custom.custom_name else oem.name
        oem_user.display_email = custom.custom_email if custom and custom.custom_email else oem.email
        oem_user.display_phone = custom.custom_phone if custom and custom.custom_phone else oem.phone
        oem_user.display_city = custom.custom_city if custom and custom.custom_city else oem.city
        oem_user.has_customizations = bool(custom)

        disabled_oems_with_custom_data.append(oem_user)

    # Pagination
    p = Paginator(disabled_oems_with_custom_data, 50)
    page = request.GET.get('page')
    disabled_page = p.get_page(page)

    context = {
        'disabled_oems': disabled_oems_with_custom_data,
        'oems': active_oems,
        'disabled': disabled_page,
        'disabled_oem_users': disabled_oem_users  # Optional: might be redundant
    }

    return render(request, 'solicitations/oems/disabled_oems.html', context)

## view to disable a particular oem
def disable_oem(request):
    if request.method == 'POST':
        oem_id = request.POST.get('oem')
        reason = request.POST.get('reason')

        # Get the OEMUser object specific to the logged-in user
        oem_user = get_object_or_404(OEMUser, oem_id=oem_id, user=request.user)

        # Disable the OEM for this user and provide a reason
        oem_user.is_disabled = True
        oem_user.reason = reason
        oem_user.save()

        messages.success(request, f"OEM {oem_user.oem.name} has been disabled.")
        return redirect('solicitations:active-oems')

    return HttpResponseForbidden("Invalid request")

## view to enable a particular oem
def enable_oem(request, oem):
    if request.method == "POST":
        # Fetch the OEMUser object for the logged-in user
        enable_oem = get_object_or_404(OEMUser, id=oem, user=request.user)

        # Enable the OEM for this user
        enable_oem.is_disabled = False 
        enable_oem.save()

        # Clear the reason for disabling
        enable_oem.reason = ""
        enable_oem.save()

        # Success message
        messages.success(request, f"OEM has been successfully enabled.")

        return redirect('solicitations:disabled-oems')
    else:
        return redirect('solicitations:disabled-oems')
    
## View to edit a particular oem 
def edit_oem(request, oem):
    """View to edit a particular oem with user-specific customizations"""
    oem_obj = get_object_or_404(OEM, id=oem)
    
    # Check if the logged-in user is assigned to this OEM (regardless of enabled/disabled status)
    user_oem = OEMUser.objects.filter(user=request.user, oem=oem_obj).first()
    if not user_oem:
        return HttpResponseForbidden("You do not have permission to edit this OEM.")
    
    # Get the disabled status for context
    is_disabled = user_oem.is_disabled
    
    # Get or create the user's customization for this OEM
    customization, created = UserOEMCustomization.objects.get_or_create(
        user=request.user,
        oem=oem_obj
    )
    
    if request.method == "POST":
        form = UserOEMCustomizationForm(request.POST, instance=customization)
        if form.is_valid():
            form.save()
            
            # Different success message based on disabled status
            if is_disabled:
                messages.success(request, f"Your customization for disabled OEM saved successfully. You can enable this OEM when ready.")
            else:
                messages.success(request, f"Your personal OEM customization saved successfully.")
            
            return redirect('solicitations:oem-detail', oem=oem_obj.id)
    else:
        form = UserOEMCustomizationForm(instance=customization)
        
        # Pre-fill with OEM values if no customizations exist yet
        if created:
            initial_data = {
                'custom_name': oem_obj.name,
                'custom_email': oem_obj.email,
                'custom_phone': oem_obj.phone,
                'custom_fax': oem_obj.fax,
                'custom_city': oem_obj.city,
                'custom_street': oem_obj.street,
                'custom_postal_code': oem_obj.postal_code,
                'custom_poc': oem_obj.poc,
            }
            form = UserOEMCustomizationForm(initial=initial_data, instance=customization)
    
    context = {
        'form': form, 
        'oem': oem_obj,
        'is_disabled': is_disabled,
        'user_oem': user_oem
    }
    
    return render(request, 'solicitations/oems/edit_oem.html', context)

def validate_multiple_emails(email_string):
    """
    Validate multiple emails separated by semicolons or commas
    Returns: (is_valid, cleaned_email_string)
    """
    if not email_string or not email_string.strip():
        return False, ""
    
    # Split by semicolon or comma and clean up
    emails = re.split(r'[;,]', email_string)
    valid_emails = []
    
    for email in emails:
        email = email.strip()
        if email:  # Skip empty strings
            try:
                validate_email(email)
                valid_emails.append(email)
            except ValidationError:
                return False, email_string  # Return original if any email is invalid
    
    if not valid_emails:
        return False, email_string
    
    # Return cleaned email string with semicolon separator
    return True, '; '.join(valid_emails)

def add_oem(request):
    """View to handle manual OEM addition - MODIFIED to use UserOEMCustomization"""
    if request.method == 'POST':
        logger.info("Received POST data for manual add")
        
        try:
            # Extract OEM data from form
            name = request.POST.get('name')
            cage = request.POST.get('cage')
            email = request.POST.get('email')
            phone = request.POST.get('phone', '') or '-'
            fax = request.POST.get('fax', '') or '-'
            city = request.POST.get('city', '') or '-'
            street = request.POST.get('street', '') or '-'
            postal_code = request.POST.get('postal_code', '') or '-'
            poc = request.POST.get('poc', '') or '-'
            override_existing = request.POST.get('override_existing', False) 
            
            logger.info(f"Processing OEM with cage code: {cage}")
            
            # Validate required fields
            required_fields = {'name': name, 'cage': cage, 'email': email}
            missing_fields = [field for field, value in required_fields.items() if not value]
            
            if missing_fields:
                error_msg = f"Missing required fields: {', '.join(missing_fields)}"
                logger.error(error_msg)
                messages.error(request, error_msg)
                return redirect('solicitations:active-oems')
            
            # Validate email format
            is_valid, cleaned_email = validate_multiple_emails(email)
            if not is_valid:
                error_msg = "Invalid email format. Please use valid email addresses separated by semicolons or commas."
                logger.error(error_msg)
                messages.error(request, error_msg)
                return redirect('solicitations:active-oems')
            
            email = cleaned_email
            
            # Check if user already has this OEM enabled
            user_has_oem = OEMUser.objects.filter(
                user=request.user,
                oem__cage__iexact=cage,
                is_disabled=False
            ).exists()
            
            if user_has_oem and not override_existing:
                logger.warning(f"Duplicate cage code detected for user: {cage}")
                # Store data in session and show duplicate modal
                request.session['duplicate_oem_data'] = {
                    'name': name, 'cage': cage, 'email': email, 'phone': phone,
                    'fax': fax, 'city': city, 'street': street, 
                    'postal_code': postal_code, 'poc': poc,
                    'existing_oem_name': OEM.objects.filter(cage__iexact=cage).first().name
                }
                request.session['show_duplicate_modal'] = True
                return redirect('solicitations:active-oems')
            
            elif user_has_oem and override_existing:
                # MODIFIED: Create/update UserOEMCustomization instead of modifying shared OEM
                existing_oem = OEM.objects.filter(cage__iexact=cage).first()
                
                logger.info(f"MANUAL UPDATE: Creating/updating UserOEMCustomization for CAGE {cage}")
                
                # Create or update user-specific customization
                customization, created = UserOEMCustomization.objects.get_or_create(
                    user=request.user,
                    oem=existing_oem,
                    defaults={
                        'custom_name': name,
                        'custom_email': email,
                        'custom_phone': phone,
                        'custom_fax': fax,
                        'custom_city': city,
                        'custom_street': street,
                        'custom_postal_code': postal_code,
                        'custom_poc': poc,
                    }
                )
                
                if not created:
                    # Update existing customization
                    customization.custom_name = name
                    customization.custom_email = email
                    customization.custom_phone = phone
                    customization.custom_fax = fax
                    customization.custom_city = city
                    customization.custom_street = street
                    customization.custom_postal_code = postal_code
                    customization.custom_poc = poc
                    customization.save()
                
                logger.info(f"MANUAL UPDATE: UserOEMCustomization {'created' if created else 'updated'} for CAGE {cage}")
                messages.success(request, f"Your personal OEM data updated successfully for {name}")
                
                # Clear session data
                if 'duplicate_oem_data' in request.session:
                    del request.session['duplicate_oem_data']
                if 'show_duplicate_modal' in request.session:
                    del request.session['show_duplicate_modal']
                    
            else:
                # Check if OEM exists globally
                existing_oem = OEM.objects.filter(cage__iexact=cage).first()
                
                if existing_oem:
                    # MODIFIED: Create UserOEMCustomization instead of updating shared OEM
                    logger.info(f"MANUAL ADD: Creating UserOEMCustomization for existing OEM with CAGE {cage}")
                    
                    # Create user association
                    OEMUser.objects.get_or_create(
                        user=request.user, 
                        oem=existing_oem, 
                        defaults={'is_disabled': False}
                    )
                    
                    # Create user-specific customization
                    customization, created = UserOEMCustomization.objects.get_or_create(
                        user=request.user,
                        oem=existing_oem,
                        defaults={
                            'custom_name': name,
                            'custom_email': email,
                            'custom_phone': phone,
                            'custom_fax': fax,
                            'custom_city': city,
                            'custom_street': street,
                            'custom_postal_code': postal_code,
                            'custom_poc': poc,
                        }
                    )
                    
                    if not created:
                        # Update existing customization
                        customization.custom_name = name
                        customization.custom_email = email
                        customization.custom_phone = phone
                        customization.custom_fax = fax
                        customization.custom_city = city
                        customization.custom_street = street
                        customization.custom_postal_code = postal_code
                        customization.custom_poc = poc
                        customization.save()
                    
                    logger.info(f"MANUAL ADD: UserOEMCustomization {'created' if created else 'updated'} for existing OEM with CAGE {cage}")
                    messages.success(request, f"OEM added to your list with your custom data: {name}")
                else:
                    # Create new OEM with base data
                    logger.info(f"MANUAL ADD: Creating new OEM for CAGE {cage}")
                    new_oem = OEM.objects.create(
                        name=name, 
                        cage=cage, 
                        email=email, 
                        phone=phone,
                        fax=fax, 
                        city=city, 
                        street=street, 
                        postal_code=postal_code, 
                        poc=poc,
                        data_source='manual',
                        manual_override=True
                    )
                    
                    # Associate with current user
                    OEMUser.objects.create(user=request.user, oem=new_oem, is_disabled=False)
                    
                    logger.info(f"MANUAL ADD: New OEM created for CAGE {cage}")
                    messages.success(request, f"New OEM created and added to your list: {name}")
            
        except Exception as e:
            logger.error(f"Error processing OEM: {str(e)}")
            logger.error(traceback.format_exc())
            messages.error(request, f"Error processing OEM: {str(e)}")
            
        return redirect('solicitations:active-oems')
    
    return redirect('solicitations:active-oems')

@require_POST
def clear_duplicate_flag(request):
    """Clear duplicate modal flag from session"""
    if 'show_duplicate_modal' in request.session:
        del request.session['show_duplicate_modal']
    if 'duplicate_oem_data' in request.session:
        del request.session['duplicate_oem_data']
    return JsonResponse({'status': 'success'})

def import_oem(request):
    """View to handle OEM import from Excel file with user-specific customizations"""
    if request.method == 'POST':
        logger.info("="*50)
        logger.info("Received Excel import request")
        
        override_duplicates = request.POST.get('override_duplicates', False)
        failed_rows = []
        failed_oems_created = []  # Track failed OEMs that were created as disabled
        
        if override_duplicates and 'excel_data' in request.session:
            try:
                df = pd.read_json(request.session['excel_data'])
            except Exception as e:
                messages.error(request, "Session data expired. Please re-upload the file.")
                return redirect('solicitations:active-oems')
        elif 'excel_file' not in request.FILES:
            messages.error(request, "No file uploaded.")
            return redirect('solicitations:active-oems')
        else:
            excel_file = request.FILES['excel_file']
            if not excel_file.name.endswith(('.xlsx', '.xls')):
                messages.error(request, "Unsupported file format.")
                return redirect('solicitations:active-oems')
            try:
                df = pd.read_excel(excel_file)
            except Exception as e:
                messages.error(request, f"Error reading Excel file: {e}")
                return redirect('solicitations:active-oems')

        required_columns = ['Name', 'Cage', 'Email']
        if any(col not in df.columns for col in required_columns):
            messages.error(request, "Missing required columns.")
            return redirect('solicitations:active-oems')

        if not override_duplicates:
            # Check for duplicates only within the current user's OEMs
            user_oem_cages = set(
                OEM.objects.filter(
                    oemuser__user=request.user,
                    oemuser__is_disabled=False
                ).values_list('cage', flat=True)
            )
            
            duplicate_cages = [
                str(row['Cage']).strip().upper()
                for _, row in df.iterrows()
                if str(row['Cage']).strip().upper() in [cage.upper() for cage in user_oem_cages]
            ]
            
            if duplicate_cages:
                request.session['excel_data'] = df.to_json()
                request.session['show_import_duplicate_modal'] = True
                messages.warning(request, f"Found {len(duplicate_cages)} duplicate cage codes in your OEM list.")
                return redirect('solicitations:active-oems')

        success_count = skip_count = error_count = override_count = failed_disabled_count = 0

        def get_value_or_default(row, column, default="-", max_length=None):
            value = str(row[column]).strip() if column in row and not pd.isna(row[column]) else default
            return value[:max_length] if max_length and len(value) > max_length else value

        def create_failed_oem_as_disabled(row, index, failure_reason):
            """Create failed OEM data as disabled entry for the user"""
            try:
                cage = str(row['Cage']).strip().upper()
                
                # Use raw email even if invalid (for reference)
                raw_email = str(row['Email']).strip() if 'Email' in row and not pd.isna(row['Email']) else 'invalid@email.com'
                
                # Check if OEM exists globally first
                existing_oem = OEM.objects.filter(cage__iexact=cage).first()
                
                if existing_oem:
                    # OEM exists globally - create disabled user association and customization
                    oem_user, created = OEMUser.objects.get_or_create(
                        user=request.user, 
                        oem=existing_oem,
                        defaults={
                            'is_disabled': True,
                            'reason': f"Import failed: {failure_reason}"
                        }
                    )
                    
                    if not created:
                        # Update existing association to disabled
                        oem_user.is_disabled = True
                        oem_user.reason = f"Import failed: {failure_reason}"
                        oem_user.save()
                    
                    # Create user-specific customization with the failed data
                    customization, created = UserOEMCustomization.objects.get_or_create(
                        user=request.user,
                        oem=existing_oem,
                        defaults={
                            'custom_name': str(row['Name']).strip() if 'Name' in row and not pd.isna(row['Name']) else 'Unknown',
                            'custom_email': raw_email,
                            'custom_phone': get_value_or_default(row, 'Phone', max_length=50),
                            'custom_city': get_value_or_default(row, 'City'),
                            'custom_street': get_value_or_default(row, 'Street'),
                            'custom_postal_code': get_value_or_default(row, 'Zip Code'),
                            'custom_poc': get_value_or_default(row, 'POC'),
                            'custom_fax': get_value_or_default(row, 'Fax'),
                        }
                    )
                    
                    if not created:
                        # Update existing customization with failed data
                        customization.custom_name = str(row['Name']).strip() if 'Name' in row and not pd.isna(row['Name']) else 'Unknown'
                        customization.custom_email = raw_email
                        customization.custom_phone = get_value_or_default(row, 'Phone', max_length=50)
                        customization.custom_city = get_value_or_default(row, 'City')
                        customization.custom_street = get_value_or_default(row, 'Street')
                        customization.custom_postal_code = get_value_or_default(row, 'Zip Code')
                        customization.custom_poc = get_value_or_default(row, 'POC')
                        customization.custom_fax = get_value_or_default(row, 'Fax')
                        customization.save()
                    
                    failed_oems_created.append(cage)
                    logger.info(f"Row {index}: Created disabled OEM association for existing cage {cage} (Reason: {failure_reason})")
                    
                else:
                    # Create new OEM with failed data as disabled
                    new_oem = OEM.objects.create(
                        name=str(row['Name']).strip() if 'Name' in row and not pd.isna(row['Name']) else 'Unknown',
                        cage=cage,
                        email=raw_email,  # Use raw email even if invalid
                        phone=get_value_or_default(row, 'Phone', max_length=50),
                        fax=get_value_or_default(row, 'Fax'),
                        city=get_value_or_default(row, 'City'),
                        street=get_value_or_default(row, 'Street'),
                        postal_code=get_value_or_default(row, 'Zip Code'),
                        poc=get_value_or_default(row, 'POC'),
                        data_source='import',
                        manual_override=True
                    )
                    
                    # Create disabled user association
                    OEMUser.objects.create(
                        user=request.user, 
                        oem=new_oem, 
                        is_disabled=True,
                        reason=f"Import failed: {failure_reason}"
                    )
                    
                    failed_oems_created.append(cage)
                    logger.info(f"Row {index}: Created new disabled OEM for cage {cage} (Reason: {failure_reason})")
                
                return True
                
            except Exception as e:
                logger.error(f"Failed to create disabled OEM for row {index}: {str(e)}")
                return False

        for index, row in df.iterrows():
            try:
                with transaction.atomic():
                    # Check for missing required fields
                    missing = [col for col in required_columns if pd.isna(row[col]) or str(row[col]).strip() == '']
                    if missing:
                        logger.warning(f"Row {index}: Missing values for {missing}. Creating as disabled.")
                        
                        # Create failed OEM as disabled
                        if create_failed_oem_as_disabled(row, index, f"Missing required fields: {', '.join(missing)}"):
                            failed_disabled_count += 1
                        else:
                            error_count += 1
                            failed_rows.append(row.to_dict())
                        continue

                    # Validate email
                    email_value = str(row['Email']).strip()
                    is_valid, cleaned_email = validate_multiple_emails(email_value)
                    if not is_valid:
                        logger.warning(f"Row {index}: Invalid email '{email_value}'. Creating as disabled.")
                        
                        # Create failed OEM as disabled
                        if create_failed_oem_as_disabled(row, index, f"Invalid email format: {email_value}"):
                            failed_disabled_count += 1
                        else:
                            error_count += 1
                            failed_rows.append(row.to_dict())
                        continue

                    cage = str(row['Cage']).strip().upper()
                    
                    # Check if user already has this OEM
                    user_has_oem = OEMUser.objects.filter(
                        user=request.user,
                        oem__cage__iexact=cage,
                        is_disabled=False
                    ).exists()

                    if user_has_oem and override_duplicates:
                        # Create/update user-specific customization instead of shared OEM
                        oem = OEM.objects.filter(cage__iexact=cage).first()
                        customization, created = UserOEMCustomization.objects.get_or_create(
                            user=request.user,
                            oem=oem,
                            defaults={
                                'custom_name': str(row['Name']).strip(),
                                'custom_email': cleaned_email,
                                'custom_phone': get_value_or_default(row, 'Phone', max_length=50),
                                'custom_city': get_value_or_default(row, 'City'),
                                'custom_street': get_value_or_default(row, 'Street'),
                                'custom_postal_code': get_value_or_default(row, 'Zip Code'),
                                'custom_poc': get_value_or_default(row, 'POC'),
                                'custom_fax': get_value_or_default(row, 'Fax'),
                            }
                        )
                        
                        if not created:
                            # Update existing customization
                            customization.custom_name = str(row['Name']).strip()
                            customization.custom_email = cleaned_email
                            customization.custom_phone = get_value_or_default(row, 'Phone', max_length=50)
                            customization.custom_city = get_value_or_default(row, 'City')
                            customization.custom_street = get_value_or_default(row, 'Street')
                            customization.custom_postal_code = get_value_or_default(row, 'Zip Code')
                            customization.custom_poc = get_value_or_default(row, 'POC')
                            customization.custom_fax = get_value_or_default(row, 'Fax')
                            customization.save()
                        
                        override_count += 1
                        logger.info(f"Row {index}: Updated user customization for cage {cage}")

                    elif not user_has_oem:
                        # Check if OEM exists globally
                        existing_oem = OEM.objects.filter(cage__iexact=cage).first()
                        
                        if existing_oem:
                            # OEM exists globally - create user association and customization
                            OEMUser.objects.get_or_create(
                                user=request.user, 
                                oem=existing_oem,
                                defaults={'is_disabled': False}
                            )
                            
                            # Create or update user-specific customization with import data
                            customization, created = UserOEMCustomization.objects.get_or_create(
                                user=request.user,
                                oem=existing_oem,
                                defaults={
                                    'custom_name': str(row['Name']).strip(),
                                    'custom_email': cleaned_email,
                                    'custom_phone': get_value_or_default(row, 'Phone', max_length=50),
                                    'custom_city': get_value_or_default(row, 'City'),
                                    'custom_street': get_value_or_default(row, 'Street'),
                                    'custom_postal_code': get_value_or_default(row, 'Zip Code'),
                                    'custom_poc': get_value_or_default(row, 'POC'),
                                    'custom_fax': get_value_or_default(row, 'Fax'),
                                }
                            )
                            
                            if not created:
                                # Update existing customization
                                customization.custom_name = str(row['Name']).strip()
                                customization.custom_email = cleaned_email
                                customization.custom_phone = get_value_or_default(row, 'Phone', max_length=50)
                                customization.custom_city = get_value_or_default(row, 'City')
                                customization.custom_street = get_value_or_default(row, 'Street')
                                customization.custom_postal_code = get_value_or_default(row, 'Zip Code')
                                customization.custom_poc = get_value_or_default(row, 'POC')
                                customization.custom_fax = get_value_or_default(row, 'Fax')
                                customization.save()
                            
                            success_count += 1
                            logger.info(f"Row {index}: {'Created' if created else 'Updated'} user customization for cage {cage}")
                        else:
                            # Create new OEM with base data
                            new_oem = OEM.objects.create(
                                name=str(row['Name']).strip(),
                                cage=cage,
                                email=cleaned_email,
                                phone=get_value_or_default(row, 'Phone', max_length=50),
                                fax=get_value_or_default(row, 'Fax'),
                                city=get_value_or_default(row, 'City'),
                                street=get_value_or_default(row, 'Street'),
                                postal_code=get_value_or_default(row, 'Zip Code'),
                                poc=get_value_or_default(row, 'POC'),
                                data_source='import',
                                manual_override=True
                            )
                            
                            # Create user association
                            OEMUser.objects.create(user=request.user, oem=new_oem, is_disabled=False)
                            success_count += 1
                            logger.info(f"Row {index}: Created new OEM for cage {cage}")
                    else:
                        skip_count += 1
                        logger.info(f"Row {index}: Skipped duplicate cage {cage} for user {request.user.username}")

            except (DataError, IntegrityError) as db_err:
                logger.error(f"Row {index} database error: {db_err}")
                
                # Try to create as disabled OEM
                if create_failed_oem_as_disabled(row, index, f"Database error: {str(db_err)}"):
                    failed_disabled_count += 1
                else:
                    failed_rows.append(row.to_dict())
                    error_count += 1
                continue
            except Exception as e:
                logger.error(f"Row {index} error: {str(e)}")
                logger.error(traceback.format_exc())
                
                # Try to create as disabled OEM
                if create_failed_oem_as_disabled(row, index, f"Processing error: {str(e)}"):
                    failed_disabled_count += 1
                else:
                    failed_rows.append(row.to_dict())
                    error_count += 1
                continue

        # Save failed rows to Excel (only rows that couldn't be saved at all)
        if failed_rows:
            try:
                failed_df = pd.DataFrame(failed_rows)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                export_dir = os.path.join(settings.MEDIA_ROOT, "failed_imports")
                os.makedirs(export_dir, exist_ok=True)
                export_filename = f"failed_oems_{timestamp}.xlsx"
                export_path = os.path.join(export_dir, export_filename)
                failed_df.to_excel(export_path, index=False)
                download_link = f"{settings.MEDIA_URL}failed_imports/{export_filename}"
                request.session['failed_import_file'] = download_link
            except Exception as e:
                logger.error(f"Error saving failed rows file: {e}")

        # Clear session
        for key in ['import_file_data', 'excel_data', 'show_import_duplicate_modal']:
            request.session.pop(key, None)

        # Enhanced success messages
        total_processed = success_count + override_count
        if total_processed > 0:
            messages.success(
                request,
                f"Successfully processed {total_processed} OEMs. "
                f"{success_count} new, {override_count} updated (your personal data only)."
            )
        if skip_count > 0:
            messages.info(request, f"{skip_count} OEMs skipped (already in your list).")
        if failed_disabled_count > 0:
            messages.info(
                request,
                f"{failed_disabled_count} OEMs with errors were saved as disabled in your list. "
                f"You can review and fix them later in the disabled OEMs section."
            )
        if error_count > 0:
            if 'failed_import_file' in request.session:
                messages.warning(
                    request,
                    f"{error_count} rows could not be processed at all. "
                    f"<a href='{request.session['failed_import_file']}' target='_blank'>Download failed rows</a>",
                    extra_tags='safe'
                )
            else:
                messages.warning(request, f"{error_count} rows could not be processed at all.")

        if failed_oems_created:
            logger.info(f"Created {len(failed_oems_created)} disabled OEMs for user {request.user.username}: {failed_oems_created}")

        logger.info("="*50)
        return redirect('solicitations:active-oems')

    return redirect('solicitations:active-oems')

@require_POST
def clear_import_duplicate_flag(request):
    """Clear import duplicate modal flag from session"""
    if 'show_import_duplicate_modal' in request.session:
        del request.session['show_import_duplicate_modal']
    if 'import_file_data' in request.session:
        del request.session['import_file_data']
    if 'excel_data' in request.session:
        del request.session['excel_data']
    return JsonResponse({'status': 'success'})


def delete_oem(request, oem_id):
   """Delete a single OEM from user's list"""
   if request.method == 'POST':
       try:
           # Get the OEM
           oem = get_object_or_404(OEM, id=oem_id)
           
           # Check if user has access to this OEM
           oem_user = get_object_or_404(OEMUser, user=request.user, oem=oem)
           
           # Get user-specific data for the success message
           user_data = get_user_oem_data(request.user, oem)
           oem_name = user_data['name']
           
           # Delete the user's association with this OEM
           oem_user.delete()
           
           # Delete user's customization if it exists
           try:
               customization = UserOEMCustomization.objects.get(user=request.user, oem=oem)
               customization.delete()
           except UserOEMCustomization.DoesNotExist:
               pass
           
           # Check if no other users are associated with this OEM
           if not OEMUser.objects.filter(oem=oem).exists():
               # If this was the last user, delete the OEM entirely
               oem.delete()
               logger.info(f"Deleted OEM {oem.cage} entirely as no users were associated")
           
           messages.success(request, f"Successfully deleted {oem_name} from your account.")
           logger.info(f"User {request.user.username} deleted OEM {oem.cage}")
           
       except Exception as e:
           logger.error(f"Error deleting OEM {oem_id} for user {request.user.username}: {e}")
           messages.error(request, "Error deleting OEM. Please try again.")
   
   return redirect('solicitations:active-oems')


def bulk_delete_oems(request):
    """Delete multiple OEMs from user's list"""
    if request.method == 'POST':
        try:
            oem_ids = request.POST.get('oem_ids', '')
            if not oem_ids:
                messages.error(request, "No OEMs selected for deletion.")
                return redirect('solicitations:active-oems')
            
            # Handle "select all" case
            if oem_ids == 'all':
                # Get all OEM IDs that the user has access to
                user_oems = OEMUser.objects.filter(user=request.user).select_related('oem')
                oem_id_list = [oem_user.oem.id for oem_user in user_oems]
                
                if not oem_id_list:
                    messages.warning(request, "No OEMs found to delete.")
                    return redirect('solicitations:active-oems')
            else:
                # Parse the comma-separated IDs
                try:
                    oem_id_list = [int(id.strip()) for id in oem_ids.split(',') if id.strip()]
                except ValueError:
                    messages.error(request, "Invalid OEM IDs provided.")
                    return redirect('solicitations:active-oems')
                
                if not oem_id_list:
                    messages.error(request, "No valid OEMs selected for deletion.")
                    return redirect('solicitations:active-oems')
            
            deleted_count = 0
            deleted_names = []
            skipped_count = 0
            
            with transaction.atomic():
                for oem_id in oem_id_list:
                    try:
                        # Get the OEM
                        oem = OEM.objects.get(id=oem_id)
                        
                        # Check if user has access to this OEM
                        oem_user = OEMUser.objects.filter(user=request.user, oem=oem).first()
                        if not oem_user:
                            skipped_count += 1
                            continue  # Skip if user doesn't have access
                        
                        # Get user-specific data for the success message
                        user_data = get_user_oem_data(request.user, oem)
                        deleted_names.append(user_data['name'])
                        
                        # Delete the user's association with this OEM
                        oem_user.delete()
                        
                        # Delete user's customization if it exists
                        try:
                            customization = UserOEMCustomization.objects.get(user=request.user, oem=oem)
                            customization.delete()
                        except UserOEMCustomization.DoesNotExist:
                            pass
                        
                        # Check if no other users are associated with this OEM
                        if not OEMUser.objects.filter(oem=oem).exists():
                            # If this was the last user, delete the OEM entirely
                            oem.delete()
                            logger.info(f"Deleted OEM {oem.cage} entirely as no users were associated")
                        
                        deleted_count += 1
                        
                    except OEM.DoesNotExist:
                        logger.warning(f"OEM {oem_id} not found during bulk delete")
                        skipped_count += 1
                        continue
                    except Exception as e:
                        logger.error(f"Error deleting OEM {oem_id} during bulk delete: {e}")
                        skipped_count += 1
                        continue
            
            # Prepare success/warning messages
            if deleted_count > 0:
                if deleted_count == 1:
                    messages.success(request, f"Successfully deleted {deleted_names[0]} from your account.")
                elif deleted_count <= 3:
                    names_str = ", ".join(deleted_names)
                    messages.success(request, f"Successfully deleted {deleted_count} OEMs: {names_str}")
                else:
                    messages.success(request, f"Successfully deleted {deleted_count} OEMs from your account.")
                
                logger.info(f"User {request.user.username} bulk deleted {deleted_count} OEMs")
            
            if skipped_count > 0:
                if deleted_count > 0:
                    messages.warning(request, f"Note: {skipped_count} OEM(s) were skipped (no access or not found).")
                else:
                    messages.warning(request, f"No OEMs were deleted. {skipped_count} OEM(s) were skipped (no access or not found).")
            
            if deleted_count == 0 and skipped_count == 0:
                messages.warning(request, "No OEMs were deleted. Please check your selections.")
                
        except Exception as e:
            logger.error(f"Error during bulk delete for user {request.user.username}: {e}")
            messages.error(request, "Error deleting OEMs. Please try again.")
    
    return redirect('solicitations:active-oems')

#### FUNCTIONS FOR THE ADMIN TO INTERACT WITH CRON JOB CONFIGURATIONS

def update_github_workflow(request):
    workflow = GitHubWorkflow.objects.first() or GitHubWorkflow()

    if request.method == "POST":
        form = GitHubWorkflowForm(request.POST, instance=workflow)
        if form.is_valid():
            form.save()
            update_yaml_file(workflow.cron_schedule)  # Update workflow
            commit_and_push_changes()  # Push to GitHub
            return redirect("solicitations:home")  # Redirect after saving

    else:
        form = GitHubWorkflowForm(instance=workflow)

    return render(request, "solicitations/workflows.html", {"form": form})


def update_yaml_file(new_cron):
    """Updates the cron schedule in the GitHub Actions workflow file while preserving formatting."""
    try:
        yaml = YAML()
        yaml.preserve_quotes = True  # Keep formatting intact

        # Load the existing YAML file
        with open(WORKFLOW_FILE_PATH, "r") as f:
            workflow_data = yaml.load(f) or {}  # Load YAML, default to empty dict if None

        print("Before Update:", workflow_data)  # Debugging

        # Ensure the necessary structure exists
        if "on" not in workflow_data:
            workflow_data["on"] = {}
        if "schedule" not in workflow_data["on"]:
            workflow_data["on"]["schedule"] = []

        # Update the cron job schedule
        if workflow_data["on"]["schedule"]:
            workflow_data["on"]["schedule"][0]["cron"] = new_cron  # Modify existing cron
        else:
            workflow_data["on"]["schedule"].append({"cron": new_cron})  # Add cron if missing

        # Save the updated YAML file
        with open(WORKFLOW_FILE_PATH, "w") as f:
            yaml.dump(workflow_data, f)

        print("After Update:", workflow_data)  # Debugging
        return {"success": True, "message": "Cron job updated successfully."}

    except Exception as e:
        return {"success": False, "error": str(e)}


def commit_and_push_changes():
    """Commits and pushes the updated workflow file to GitHub."""
    repo_path = r"C:\Users\Staphord Bengesi\Desktop\DLA"
    repo = Repo(repo_path)
    repo.git.add(WORKFLOW_FILE_PATH)
    repo.index.commit("Updated GitHub Actions cron schedule")
    repo.remote("origin").push()

# view to show client detail
def user_profile(request, client):
    client_user = request.user
    logo_form = LogoUpdateForm(instance=client_user)
    user_form = UserUpdateForm(instance=client_user)
    password_form = CustomPasswordChangeForm(user=client_user) 
    
    if request.method == 'POST':
        if 'logo_update' in request.POST:
            print("Processing logo update")
            print(f"FILES: {request.FILES}")
            
            logo_form = LogoUpdateForm(request.POST, request.FILES, instance=client_user)
            if logo_form.is_valid():
                print("Logo form is valid")
                logo_form.save()
                messages.success(request, 'Your logo has been updated successfully!')
                return redirect('solicitations:user-profile', client=client)
            else:
                print(f"Logo form errors: {logo_form.errors}")
                messages.error(request, 'Error updating logo. Please check the form.')
                
        elif 'details_update' in request.POST:
            user_form = UserUpdateForm(request.POST, instance=client_user)
            if user_form.is_valid():
                user_form.save()
                messages.success(request, 'Your profile has been updated successfully!')
                return redirect('solicitations:user-profile', client=client)
            else:
                messages.error(request, 'Error updating profile. Please check the form.')
                
        elif 'password_update' in request.POST:  
            password_form = CustomPasswordChangeForm(user=client_user, data=request.POST)
            if password_form.is_valid():
                password_form.save()
                # Important: Update the session to prevent logout after password change
                update_session_auth_hash(request, client_user)
                messages.success(request, 'Your password has been updated successfully!')
                return redirect('solicitations:user-profile', client=client)
            else:
                messages.error(request, 'Error updating password. Please check the form.')    
    
    context = {
        'client': client_user,
        'logo_form': logo_form,
        'user_form': user_form,
        'password_form': password_form,  
    }
    
    return render(request, 'solicitations/clients/user-profile.html', context)

## view for sending envitation link
def invite_user(request):
    if request.method == 'POST':
        email = request.POST.get('email').lower().strip()  # Normalize email
        
        # 1. First check if user already exists
        if CustomUser.objects.filter(email=email).exists():
            messages.error(request, f"Email '{email}' is already registered.")
            return render(request, 'solicitations/clients/invite_user.html', 
                        {'entered_email': email})
        
        # 2. Create new invitation (regardless of existing ones)
        invitation = Invitation(email=email)
        invitation.save()
        
        # 3. Send email with new invitation using standard SMTP backend
        invite_url = request.build_absolute_uri(
            reverse('register_with_invitation', args=[str(invitation.token)])
        )
        
        subject = 'Your Invitation'
        message = f'''
        Hello,
        
        Here's your registration link:
        {invite_url}
        
        Expires: {invitation.expires_at.strftime('%Y-%m-%d')}
        '''
        
        # Use standard SMTP backend for this specific email
        connection = get_connection(
            backend='django.core.mail.backends.smtp.EmailBackend',
            host='gilgaltech.com',
            port=587,
            username='info@gilgaltech.com',
            password='info@0213',
            use_tls=True,
        )
        
        send_mail(
            subject, 
            message, 
            'info@gilgaltech.com',  # from_email
            [email],
            connection=connection
        )
        
        messages.success(request, f"Invitation sent to {email}")
        return redirect('solicitations:invite_user')
    
    return render(request, 'solicitations/clients/invite_user.html')

def test_imap_connection(config):
    """Test IMAP connection for sent folder functionality"""
    try:
        import imaplib
        
        # Get IMAP settings
        if config.custom_imap_host and config.custom_imap_host.strip():
            imap_host = config.custom_imap_host.strip()
        else:
            # Auto-detect IMAP host based on SMTP host
            email_host_lower = config.email_host.lower()
            if 'gmail' in email_host_lower:
                imap_host = 'imap.gmail.com'
            elif 'outlook' in email_host_lower or 'hotmail' in email_host_lower or 'live' in email_host_lower:
                imap_host = 'imap-mail.outlook.com'
            elif 'yahoo' in email_host_lower:
                imap_host = 'imap.mail.yahoo.com'
            elif 'icloud' in email_host_lower:
                imap_host = 'imap.mail.me.com'
            else:
                if config.email_host.startswith('smtp.'):
                    imap_host = config.email_host.replace('smtp.', 'imap.')
                elif config.email_host.startswith('mail.'):
                    imap_host = config.email_host
                else:
                    imap_host = f"mail.{config.email_host}"
        
        imap_port = config.custom_imap_port or 993
        
        # Try to connect
        imap_server = imaplib.IMAP4_SSL(imap_host, imap_port)
        imap_server.login(config.email_host_user, config.email_host_password)
        
        # Test sent folder access
        if config.custom_sent_folder and config.custom_sent_folder.strip():
            sent_folder = config.custom_sent_folder.strip()
        else:
            # Auto-detect sent folder
            email_host_lower = config.email_host.lower()
            if 'gmail' in email_host_lower:
                sent_folder = '[Gmail]/Sent Mail'
            elif 'outlook' in email_host_lower or 'hotmail' in email_host_lower or 'live' in email_host_lower:
                sent_folder = 'Sent Items'
            elif 'yahoo' in email_host_lower:
                sent_folder = 'Sent'
            elif 'icloud' in email_host_lower:
                sent_folder = 'Sent Messages'
            else:
                sent_folder = 'INBOX.Sent'
        
        # Try to select the sent folder
        status, _ = imap_server.select(sent_folder)
        if status == 'OK':
            imap_server.close()
            imap_server.logout()
            return {
                'success': True,
                'message': f'Successfully connected to {imap_host} and accessed {sent_folder}'
            }
        else:
            # Try alternative folder names
            alternative_folders = ['Sent Items', 'Sent', 'INBOX.Sent', 'Sent Messages']
            for alt_folder in alternative_folders:
                try:
                    status, _ = imap_server.select(alt_folder)
                    if status == 'OK':
                        imap_server.close()
                        imap_server.logout()
                        return {
                            'success': True,
                            'message': f'Connected to {imap_host}, found sent folder: {alt_folder}'
                        }
                except:
                    continue
            
            imap_server.close()
            imap_server.logout()
            return {
                'success': False,
                'message': f'Connected to {imap_host} but could not find sent folder'
            }
            
    except Exception as e:
        return {
            'success': False,
            'message': f'IMAP connection failed: {str(e)}'
        }

def email_config_view(request, client_id):
    client = get_object_or_404(CustomUser, id=client_id)
   
    # Extract domain from user's email for smart defaults
    user_domain = client.email.split('@')[1] if '@' in client.email else 'gmail.com'
   
    # Set smart defaults based on email domain
    if 'gmail.com' in user_domain:
        default_smtp_host = 'smtp.gmail.com'
    elif any(provider in user_domain for provider in ['outlook.com', 'hotmail.com', 'live.com']):
        default_smtp_host = 'smtp-mail.outlook.com'
    elif 'yahoo.com' in user_domain:
        default_smtp_host = 'smtp.mail.yahoo.com'
    elif 'icloud.com' in user_domain:
        default_smtp_host = 'smtp.mail.me.com'
    else:
        # For custom domains, try mail.domain.com
        default_smtp_host = f'mail.{user_domain}'
   
    # CRITICAL FIX: Don't use get_or_create during GET requests
    # Only get existing config, don't create during GET
    try:
        config = UserEmailConfig.objects.get(user=client)
        is_new_config = False
    except UserEmailConfig.DoesNotExist:
        config = None
        is_new_config = True
    
    if request.method == 'POST':
        # Handle form submission
        if config:
            # Updating existing config
            form = EmailConfigForm(request.POST, instance=config)
        else:
            # Creating new config
            form = EmailConfigForm(request.POST)
        
        if form.is_valid():
            config = form.save(commit=False)
            config.user = client  # Ensure user is set for new configs
            config.email_use_tls = True
            config.save()
            
            action = "configured" if is_new_config else "updated"
            client_name = client.get_full_name() or client.username
            
            # Test IMAP connection if enabled
            if config.save_to_sent_folder:
                imap_test = test_imap_connection(config)
                if imap_test['success']:
                    sent_folder_status = "enabled and tested successfully"
                    messages.success(request, f"IMAP connection successful! Emails will be saved to sent folder.")
                else:
                    sent_folder_status = f"enabled but IMAP test failed: {imap_test['message']}"
                    messages.warning(request, f"Sent folder feature may not work: {imap_test['message']}")
            else:
                sent_folder_status = "disabled"
            
            messages.success(
                request,
                f'Email configuration {action} successfully for {client_name}! '
                f'Email interval: {config.email_interval_display}, '
                f'Sent folder saving: {sent_folder_status}.'
            )
            
            return render(request, 'solicitations/clients/email_config_form.html', {
                'form': form,
                'client': client,
                'success_redirect': True,
                'redirect_url': reverse('solicitations:user-profile', args=[client.id])
            })
        else:
            messages.error(request, 'Please correct the errors below.')  
    else:
        # Handle GET request - display form
        if config:
            # Show existing config
            form = EmailConfigForm(instance=config)
        else:
            # Show form with default values for new config
            form = EmailConfigForm(initial={
                'email_host': default_smtp_host,
                'email_port': 587,
                'email_use_tls': True,
                'email_host_user': client.email,
                'email_host_password': '',  # Empty - user will fill this
                'default_from_email': client.email,
                'email_interval_seconds': 10,
                'save_to_sent_folder': True,
                'custom_imap_port': 993,
            })
    
    return render(request, 'solicitations/clients/email_config_form.html', {
        'form': form,
        'client': client,
    })

def test_email_config(request, client_id):
    if request.method == 'POST':
        client = get_object_or_404(CustomUser, id=client_id)
        
        try:
            config = UserEmailConfig.objects.get(user=client, is_active=True)
        except UserEmailConfig.DoesNotExist:
            return JsonResponse({'success': False, 'error': 'No email configuration found'})
        
        try:
            data = json.loads(request.body)
            test_email = data.get('test_email', client.email)
            
            # Test the email configuration
            from django.core.mail import get_connection
            connection = get_connection(
                'solicitations.email_backend.UserConfigurableEmailBackend',
                user=client
            )
            
            from django.core.mail import EmailMessage
            email = EmailMessage(
                subject='Test Email Configuration',
                body='This is a test email to verify your email configuration is working correctly.',
                from_email=config.default_from_email,
                to=[test_email],
                connection=connection
            )
            email.send()
            
            return JsonResponse({'success': True, 'message': 'Test email sent successfully!'})
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    return JsonResponse({'success': False, 'error': 'Invalid request method'})

def my_time_view(request):
    return JsonResponse({
        "browser_timezone": str(timezone.get_current_timezone()),
        "localized_time": timezone.localtime().isoformat(),
        "utc_time": timezone.now().isoformat(),
    })

##### view to check if a user has provided a logo and company initial
def check_user_profile(request):
    has_logo = bool(request.user.logo)
    has_initial = bool(request.user.company_initial)
    has_title = bool(request.user.title)
    has_personal = bool(request.user.personal_email)

    
    return JsonResponse({
        'has_logo': has_logo,
        'has_initial': has_initial,
        'has_title':has_title,
        'has_personal':has_personal 
    })

@require_http_methods(["GET"])
def check_task_status(request):
    """
    Check the status of a Django-Q task and return completion details
    Used for real-time status updates in the frontend
    """
    try:
        task_id = request.GET.get('task_id')
        
        if not task_id:
            return JsonResponse({"error": "Task ID is required"}, status=400)
        
        user = request.user
        logger.info(f"Checking task status for task_id: {task_id}, user: {user.username}")
        
        try:
            task = Task.objects.get(id=task_id)
        except Task.DoesNotExist:
            logger.error(f"Task {task_id} not found")
            return JsonResponse({"error": "Task not found"}, status=404)
        
        # Check if task belongs to this user (security check)
        if not task.name or str(user.id) not in task.name:
            logger.warning(f"User {user.username} attempted to access task {task_id} not belonging to them")
            return JsonResponse({"error": "Unauthorized"}, status=403)
        
        response_data = {
            "task_id": task_id,
            "user_id": user.id,
            "username": user.username
        }
        
        if task.stopped:
            # Task has completed
            if task.success:
                logger.info(f"Task {task_id} completed successfully")
                
                # Try to extract processed IDs from task result or name
                successful_ids = []
                failed_ids = []
                
                try:
                    # Extract IDs from task name (format: MANUAL_RFQ_U{user_id}_{signature}_{count}items_{timestamp})
                    if 'items_' in task.name:
                        # Get the original solicitation IDs that were submitted
                        # Since the script handles filtering, we need to check which ones were actually processed
                        
                        # Option 1: Check task result if it contains processed IDs
                        if hasattr(task, 'result') and task.result:
                            try:
                                if isinstance(task.result, str):
                                    result_data = json.loads(task.result)
                                else:
                                    result_data = task.result
                                
                                successful_ids = result_data.get('successful_ids', [])
                                failed_ids = result_data.get('failed_ids', [])
                            except (json.JSONDecodeError, AttributeError):
                                pass
                        
                        # Option 2: If no result data, estimate based on recent status changes
                        if not successful_ids and not failed_ids:
                            # Check SolicitationEmailStatus for recently sent items by this user
                            from django.utils import timezone
                            from datetime import timedelta
                            
                            # Look for items marked as sent in the last 10 minutes by this user
                            recent_cutoff = timezone.now() - timedelta(minutes=10)
                            recent_sent = SolicitationEmailStatus.objects.filter(
                                user=user,
                                email_sent=True,
                                email_sent_at__gte=recent_cutoff
                            ).values_list('solicitation_id', flat=True)
                            
                            successful_ids = list(recent_sent)
                            
                            logger.info(f"Estimated {len(successful_ids)} successful IDs based on recent status changes")
                
                except Exception as e:
                    logger.error(f"Error extracting processed IDs from task {task_id}: {e}")
                
                response_data.update({
                    "status": "completed",
                    "success": True,
                    "successful_ids": successful_ids,
                    "failed_ids": failed_ids,
                    "completed_at": task.stopped.isoformat() if task.stopped else None,
                    "message": f"Successfully processed {len(successful_ids)} items" + 
                              (f", {len(failed_ids)} failed" if failed_ids else "")
                })
                
            else:
                # Task failed
                logger.error(f"Task {task_id} failed")
                error_message = "Task execution failed"
                
                # Try to get error details from task result
                try:
                    if hasattr(task, 'result') and task.result:
                        if isinstance(task.result, str):
                            error_data = json.loads(task.result)
                            error_message = error_data.get('error', error_message)
                        elif isinstance(task.result, dict):
                            error_message = task.result.get('error', error_message)
                except:
                    pass
                
                response_data.update({
                    "status": "failed", 
                    "success": False,
                    "error": error_message,
                    "completed_at": task.stopped.isoformat() if task.stopped else None
                })
        
        else:
            # Task is still running or queued
            if task.started:
                logger.info(f"Task {task_id} is currently running")
                response_data.update({
                    "status": "running",
                    "started_at": task.started.isoformat(),
                    "message": "Task is currently being processed"
                })
            else:
                logger.info(f"Task {task_id} is queued")
                response_data.update({
                    "status": "pending",
                    "message": "Task is queued for processing"
                })
        
        return JsonResponse(response_data)
        
    except Exception as e:
        logger.error(f"Error checking task status: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({"error": str(e)}, status=500)

###############
@login_required
@require_http_methods(["GET"])
def check_solicitation_status(request):
    """
    Updated to check email_sent status instead of email_status
    """
    try:
        solicitation_ids = request.GET.getlist('ids[]')
        
        if not solicitation_ids:
            return JsonResponse({"error": "No solicitation IDs provided"}, status=400)
        
        try:
            solicitation_ids = [int(id) for id in solicitation_ids]
        except ValueError:
            return JsonResponse({"error": "Invalid solicitation IDs"}, status=400)
        
        # CHANGED: Get current status using email_sent field
        statuses = SolicitationEmailStatus.objects.filter(
            solicitation_id__in=solicitation_ids,
            user=request.user
        ).select_related('solicitation')
        
        status_updates = {}
        
        for status in statuses:
            # CHANGED: Use email_sent to determine status
            if status.email_sent:
                current_status = 'sent'
            else:
                current_status = 'pending'
            
            status_updates[status.solicitation_id] = {
                'status': current_status,  # CHANGED: simplified status
                'email_sent': status.email_sent,
                'email_sent_at': status.email_sent_at.isoformat() if status.email_sent_at else None
            }
        
        # For solicitations not in SolicitationEmailStatus, they are available
        existing_ids = set(status.solicitation_id for status in statuses)
        for sol_id in solicitation_ids:
            if sol_id not in existing_ids:
                status_updates[sol_id] = {
                    'status': 'available',
                    'email_sent': False,
                    'email_sent_at': None
                }
        
        return JsonResponse({
            'status_updates': status_updates,
            'user_id': request.user.id,
            'timestamp': timezone.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error checking solicitation status: {e}")
        return JsonResponse({"error": "Failed to check status"}, status=500)

@login_required
@require_http_methods(["POST"])
def mark_solicitations_processing(request):
    """
    Mark selected solicitations as processing when user starts sending RFQs
    This provides immediate UI feedback before the background task starts
    """
    try:
        data = json.loads(request.body)
        selected_ids = data.get("selected_ids", [])
        
        if not selected_ids:
            return JsonResponse({"error": "No solicitations selected"}, status=400)
        
        # Create or update SolicitationEmailStatus for selected items
        from django.utils import timezone
        
        updated_count = 0
        for sol_id in selected_ids:
            try:
                # Verify solicitation exists and user has access
                solicitation = Solicitation.objects.get(id=sol_id)
                
                # Get or create status record
                status, created = SolicitationEmailStatus.objects.get_or_create(
                    solicitation=solicitation,  # Use solicitation object, not ID
                    user=request.user,
                    defaults={
                        'email_sent': False
                    }
                )
                
                # If already exists and not sent, mark as processing (no change needed to email_sent)
                if not created and not status.email_sent:
                    # No need to update anything - just count it
                    updated_count += 1
                elif created:
                    updated_count += 1
                    
            except Solicitation.DoesNotExist:
                logger.error(f"Solicitation {sol_id} not found for user {request.user.username}")
                continue
            except Exception as e:
                logger.error(f"Error updating status for solicitation {sol_id}: {e}")
                continue
        
        logger.info(f"Marked {updated_count} solicitations as processing for user {request.user.username}")
        
        return JsonResponse({
            'message': f'Marked {updated_count} solicitations as processing',
            'updated_count': updated_count,
            'status': 'success'
        })
        
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON data"}, status=400)
    except Exception as e:
        logger.error(f"Error marking solicitations as processing: {e}")
        return JsonResponse({"error": str(e)}, status=500)
####################
@require_http_methods(["GET"])
def check_processing_status(request):
    """
    Check the processing status of specific solicitation IDs for the current user
    Returns completed IDs that are no longer in processing state
    """
    try:
        processing_ids_str = request.GET.get('processing_ids', '')
        user_id = request.GET.get('user_id')
        
        if not processing_ids_str:
            return JsonResponse({"completed_ids": []})
        
        # Parse processing IDs
        try:
            processing_ids = [int(id_str.strip()) for id_str in processing_ids_str.split(',') if id_str.strip()]
        except ValueError:
            return JsonResponse({"error": "Invalid processing IDs format"}, status=400)
        
        # Verify user matches current user
        if int(user_id) != request.user.id:
            return JsonResponse({"error": "Unauthorized"}, status=403)
        
        logger.info(f"Checking processing status for user {request.user.username} (ID: {request.user.id})")
        logger.info(f"Processing IDs to check: {processing_ids}")
        
        # Get current processing status for these IDs and this user
        current_processing = SolicitationEmailStatus.objects.filter(
            solicitation_id__in=processing_ids,
            user=request.user,
            email_status='processing'
        ).values_list('solicitation_id', flat=True)
        
        current_processing_list = list(current_processing)
        
        # Get sent status for these IDs and this user
        sent_statuses = SolicitationEmailStatus.objects.filter(
            solicitation_id__in=processing_ids,
            user=request.user,
            email_status='sent'
        ).values_list('solicitation_id', flat=True)
        
        sent_list = list(sent_statuses)
        
        # IDs that are no longer processing (either completed successfully or failed)
        completed_ids = []
        for pid in processing_ids:
            if pid not in current_processing_list:
                completed_ids.append(pid)
        
        logger.info(f"Still processing: {current_processing_list}")
        logger.info(f"Completed: {completed_ids}")
        logger.info(f"Successfully sent: {sent_list}")
        
        return JsonResponse({
            "completed_ids": completed_ids,
            "still_processing": current_processing_list,
            "successfully_sent": sent_list,
            "user_id": request.user.id
        })
        
    except Exception as e:
        logger.error(f"Error checking processing status for user {request.user.username}: {e}")
        return JsonResponse({"error": str(e)}, status=500)


@login_required  
@require_http_methods(["GET"])
def check_rfq_task_status(request):
    """
    Enhanced task status check that also returns processing details
    Note: This view is named differently to avoid conflicts with existing check_task_status
    """
    try:
        task_id = request.GET.get('task_id')
        
        if not task_id:
            return JsonResponse({"error": "Task ID required"}, status=400)
        
        # Import django-q Task model
        try:
            from django_q.models import Task
        except ImportError:
            return JsonResponse({"error": "Django-Q not available"}, status=500)
        
        # Get task details
        try:
            task = Task.objects.get(id=task_id)
        except Task.DoesNotExist:
            return JsonResponse({"error": "Task not found"}, status=404)
        
        logger.info(f"Checking task {task_id} status for user {request.user.username}")
        
        # Determine task status
        if task.success is True:
            # Task completed successfully
            # Try to get result details if available
            result = task.result or {}
            
            if isinstance(result, dict):
                successful_ids = result.get('successful_ids', [])
                failed_ids = result.get('failed_ids', [])
            else:
                # Fallback: check database for completed items
                sent_statuses = SolicitationEmailStatus.objects.filter(
                    user=request.user,
                    email_status='sent',
                    email_sent_at__gte=task.started  # Sent after task started
                ).values_list('solicitation_id', flat=True)
                
                successful_ids = list(sent_statuses)
                failed_ids = []
            
            return JsonResponse({
                "status": "completed",
                "successful_ids": successful_ids,
                "failed_ids": failed_ids,
                "task_id": task_id,
                "user_id": request.user.id
            })
            
        elif task.success is False:
            # Task failed
            error_message = getattr(task, 'result', 'Unknown error occurred')
            
            return JsonResponse({
                "status": "failed", 
                "error": str(error_message),
                "task_id": task_id,
                "user_id": request.user.id
            })
            
        else:
            # Task still running or pending
            return JsonResponse({
                "status": "running" if task.started else "pending",
                "task_id": task_id,
                "user_id": request.user.id,
                "started_at": task.started.isoformat() if task.started else None
            })
            
    except Exception as e:
        logger.error(f"Error checking task status for user {request.user.username}: {e}")
        return JsonResponse({"error": str(e)}, status=500)

######## TASK SUMMARY REPORT VIEWS ##################
@login_required
def rfq_reports_view(request):
    """
    Display RFQ task summary reports for the current user
    """
    user = request.user
    
    # Get all summaries for the current user
    summaries = RFQTaskSummary.objects.filter(user=user).order_by('-start_time')
    
    # Apply filters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    status_filter = request.GET.get('status')  # Renamed to avoid conflict
    mode = request.GET.get('mode')
    
    if date_from:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            summaries = summaries.filter(date__gte=date_from_obj)
        except ValueError:
            pass
    
    if date_to:
        try:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            summaries = summaries.filter(date__lte=date_to_obj)
        except ValueError:
            pass
    
    # Filter by status using your model's status property
    if status_filter:
        # Convert queryset to list to use the status property
        all_summaries_list = list(summaries)
        if status_filter == 'completed':
            summaries = [s for s in all_summaries_list if s.status == 'completed']
        elif status_filter == 'partial':
            summaries = [s for s in all_summaries_list if s.status == 'partial']
        elif status_filter == 'failed':
            summaries = [s for s in all_summaries_list if s.status == 'failed']
        
        # Convert back to queryset for pagination
        filtered_ids = [s.id for s in summaries]
        summaries = RFQTaskSummary.objects.filter(id__in=filtered_ids).order_by('-start_time')
    
    if mode:
        summaries = summaries.filter(processing_mode=mode)
    
    # Calculate statistics
    all_summaries = RFQTaskSummary.objects.filter(user=user)
    
    stats = {
        'total_tasks': all_summaries.count(),
        'total_sent': all_summaries.aggregate(total=Sum('total_successful_sent'))['total'] or 0,
        'total_failed': all_summaries.aggregate(total=Sum('total_failed'))['total'] or 0,
        'total_requested': all_summaries.aggregate(total=Sum('requested_solicitations'))['total'] or 0,
    }
    
    # Calculate success rate
    if stats['total_requested'] > 0:
        stats['success_rate'] = round((stats['total_sent'] / stats['total_requested']) * 100, 1)
    else:
        stats['success_rate'] = 0
    
    # This month statistics
    current_month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    this_month_summaries = all_summaries.filter(start_time__gte=current_month)
    stats['this_month_sent'] = this_month_summaries.aggregate(total=Sum('total_successful_sent'))['total'] or 0
    
    # Pagination
    paginator = Paginator(summaries, 25)  # Show 25 reports per page
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    context = {
        'summaries': page_obj,
        'stats': stats,
        'current_month': timezone.now().strftime('%B %Y'),
        'is_paginated': page_obj.has_other_pages(),
        'page_obj': page_obj,
    }
    
    return render(request, 'solicitations/rfq_summary.html', context)

@login_required
@require_http_methods(["GET"])
def get_user_state(request):
    """Get user's current selection state from database"""
    try:
        state = UserSelectionState.get_for_user(request.user)
        
        return JsonResponse({
            'selected_ids': state.selected_ids,
            'select_all_mode': state.select_all_mode,
            'processing_ids': state.processing_ids,
            'is_submitting': state.is_submitting,
            'last_updated': state.last_updated.isoformat(),
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def update_user_state(request):
    """Update user's selection state in database"""
    try:
        data = json.loads(request.body)
        state = UserSelectionState.get_for_user(request.user)
        
        action = data.get('action')
        solicitation_ids = data.get('solicitation_ids', [])
        
        if action == 'select':
            for sol_id in solicitation_ids:
                state.add_selection(sol_id)
        elif action == 'deselect':
            for sol_id in solicitation_ids:
                state.remove_selection(sol_id)
        elif action == 'select_all':
            state.set_select_all(True)
        elif action == 'clear_all':
            state.clear_selections()
        elif action == 'add_processing':
            for sol_id in solicitation_ids:
                state.add_processing(sol_id)
        elif action == 'remove_processing':
            for sol_id in solicitation_ids:
                state.remove_processing(sol_id)
        elif action == 'set_submitting':
            state.set_submitting(data.get('is_submitting', False))
        
        return JsonResponse({
            'selected_ids': state.selected_ids,
            'select_all_mode': state.select_all_mode,
            'processing_ids': state.processing_ids,
            'is_submitting': state.is_submitting,
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
@require_http_methods(["GET"])
def sync_processing_status(request):
    """Sync processing status with actual SolicitationEmailStatus"""
    try:
        state = UserSelectionState.get_for_user(request.user)
        
        # Get current processing status from database
        current_processing = list(SolicitationEmailStatus.objects.filter(
            user=request.user,
            email_status='processing'
        ).values_list('solicitation_id', flat=True))
        
        # Get sent items
        sent_items = list(SolicitationEmailStatus.objects.filter(
            user=request.user,
            email_sent=True
        ).values_list('solicitation_id', flat=True))
        
        # NEW: Get items that were processing but are now completed/failed
        old_processing_ids = state.processing_ids
        completed_ids = [id for id in old_processing_ids if id not in current_processing and id not in sent_items]
        
        # Update state
        state.processing_ids = current_processing
        
        # Remove sent items from selections
        state.selected_ids = [id for id in state.selected_ids if id not in sent_items]
        
        # If no processing items and was submitting, stop submitting
        if not current_processing and state.is_submitting:
            state.is_submitting = False
        
        state.save()
        
        return JsonResponse({
            'processing_ids': current_processing,
            'sent_ids': sent_items,
            'completed_ids': completed_ids,  # NEW: Return completed IDs
            'selected_ids': state.selected_ids,
            'is_submitting': state.is_submitting,
            'synced': True
        })
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def user_tasks_list(request):
    """
    Show all tasks/sessions for the current user
    """
    
    # Get recent sessions (last 30 days by default)
    days = int(request.GET.get('days', 30))
    start_date = datetime.now() - timedelta(days=days)
    
    sessions_qs = RFQScriptSession.objects.filter(
        user=request.user,
        start_time__gte=start_date
    ).order_by('-start_time')
    
    # Add log summary to each session
    tasks_with_summary = []
    for session in sessions_qs:
        # Build time window with small buffer
        start_buffer = session.start_time - timedelta(minutes=1)
        end_time = session.end_time or timezone.now()
        end_buffer = end_time + timedelta(minutes=1)
        
        # Combined query approach
        combined_q = Q(user=request.user, session_id=session.session_id)
        
        if hasattr(session, 'task_id') and session.task_id:
            combined_q |= Q(user=request.user, task_id=session.task_id)
        
        combined_q |= Q(
            user=request.user,
            timestamp__gte=start_buffer,
            timestamp__lte=end_buffer
        )
        
        session_logs = RFQScriptLog.objects.filter(combined_q).distinct()
        
        # Calculate summary stats
        log_summary = {
            'total_logs': session_logs.count(),
            'emails_sent': session_logs.filter(category='email', email_status='sent').count(),
            'emails_failed': session_logs.filter(category='email', email_status='failed').count(),
            'errors': session_logs.filter(level='ERROR').count(),
            'warnings': session_logs.filter(level='WARNING').count(),
        }
        
        # Add summary to session object
        session.log_summary = log_summary
        
        # Add duration_formatted if not exists
        if not hasattr(session, 'duration_formatted'):
            if session.end_time and session.start_time:
                duration = session.end_time - session.start_time
                total_seconds = int(duration.total_seconds())
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                seconds = total_seconds % 60
                
                if hours > 0:
                    session.duration_formatted = f"{hours}h {minutes}m {seconds}s"
                elif minutes > 0:
                    session.duration_formatted = f"{minutes}m {seconds}s"
                else:
                    session.duration_formatted = f"{seconds}s"
            else:
                session.duration_formatted = "In Progress" if not session.end_time else "Unknown"
        
        # Add status if not exists
        if not hasattr(session, 'status'):
            if session.end_time:
                # Determine status based on logs
                if session_logs.filter(level='ERROR').exists():
                    session.status = 'failed'
                else:
                    session.status = 'completed'
            else:
                session.status = 'running'
        
        tasks_with_summary.append(session)
    
    # Paginate sessions
    page = request.GET.get('page', 1)
    per_page = 20
    paginator = Paginator(tasks_with_summary, per_page)
    sessions_page = paginator.get_page(page)
    
    context = {
        'sessions': sessions_page,  # This should be paginated sessions
        'days_filter': days,
        'page_title': 'RFQ Tasks'
    }
    
    return render(request, 'solicitations/tasks_list.html', context)


@login_required
def task_details(request, session_id):
    """
    Show detailed logs for a specific task/session.
    Added real-time functionality.
    """
    
    # Get the session
    session = get_object_or_404(
        RFQScriptSession,
        session_id=session_id,
        user=request.user
    )
    
    # Check if real-time mode is requested
    realtime_mode = request.GET.get('realtime', 'false').lower() == 'true'
    
    # Build time window with small buffer
    start_time = session.start_time - timedelta(minutes=1)
    end_time = (session.end_time or timezone.now()) + timedelta(minutes=1)
    
    # Build combined query to find all related logs
    query_parts = []
    
    # Part 1: Direct session_id match
    query_parts.append(Q(user=request.user, session_id=session_id))
    
    # Part 2: Task_id match if available
    if hasattr(session, 'task_id') and session.task_id:
        query_parts.append(Q(user=request.user, task_id=session.task_id))
    
    # Part 3: Time-based match for orphaned logs
    query_parts.append(Q(
        user=request.user,
        timestamp__gte=start_time,
        timestamp__lte=end_time
    ))
    
    # Combine all query parts with OR
    final_query = query_parts[0]
    for query_part in query_parts[1:]:
        final_query |= query_part
    
    # Get all related logs
    all_logs = RFQScriptLog.objects.filter(final_query).select_related('user').distinct()
    
    # Apply filters
    logs_qs = all_logs.order_by('timestamp', 'id')
    
    category_filter = request.GET.get('category')
    level_filter = request.GET.get('level')
    search = request.GET.get('q')

    if category_filter:
        logs_qs = logs_qs.filter(category=category_filter)
    if level_filter:
        logs_qs = logs_qs.filter(level=level_filter)
    if search:
        logs_qs = logs_qs.filter(
            Q(message__icontains=search) |
            Q(error_details__icontains=search) |
            Q(email_subject__icontains=search) |
            Q(email_recipient__icontains=search) |
            Q(task_id__icontains=search) |
            Q(cage_code__icontains=search)
        )

    # For real-time mode, get more recent logs and limit pagination
    if realtime_mode:
        # Get last 500 logs for real-time display
        logs_qs = logs_qs.order_by('-timestamp', '-id')[:500]
        logs_qs = reversed(list(logs_qs))  # Reverse to show chronological order
        logs_page = logs_qs
        paginator = None
    else:
        # Regular pagination for static mode
        try:
            per_page = int(request.GET.get('page_size', 50))
            if per_page <= 0 or per_page > 500:
                per_page = 50
        except (ValueError, TypeError):
            per_page = 50

        page_size_options = [25, 50, 100, 200, 500]
        paginator = Paginator(logs_qs, per_page)
        page_number = request.GET.get('page', 1)
        logs_page = paginator.get_page(page_number)

    # Attach display dict to each log
    if hasattr(logs_page, '__iter__'):
        log_list = logs_page
    else:
        log_list = logs_page.object_list if hasattr(logs_page, 'object_list') else []
        
    for log in log_list:
        try:
            log.all_fields = log.to_display_dict()
        except Exception as e:
            log.all_fields = {'error': f'Display error: {e}'}

    # Summary statistics
    try:
        summary_stats = {
            'total_logs': all_logs.count(),
            'by_level': {
                'INFO': all_logs.filter(level='INFO').count(),
                'WARNING': all_logs.filter(level='WARNING').count(),
                'ERROR': all_logs.filter(level='ERROR').count(),
                'CRITICAL': all_logs.filter(level='CRITICAL').count(),
            },
            'by_category': {
                'email': all_logs.filter(category='email').count(),
                'processing': all_logs.filter(category='processing').count(),
                'status': all_logs.filter(category='status').count(),
                'oem': all_logs.filter(category='oem').count(),
                'error': all_logs.filter(category='error').count(),
                'summary': all_logs.filter(category='summary').count(),
            },
            'email_details': {
                'total_sent': all_logs.filter(category='email', email_status='sent').count(),
                'total_failed': all_logs.filter(category='email', email_status='failed').count(),
                'unique_cages': all_logs.filter(cage_code__isnull=False).values_list('cage_code', flat=True).distinct().count(),
                'unique_rfqs': all_logs.filter(rfq_id__isnull=False).values_list('rfq_id', flat=True).distinct().count(),
            }
        }
    except Exception as e:
        summary_stats = {'error': f'Stats error: {e}'}

    # Filter options
    try:
        available_categories = all_logs.values_list('category', flat=True).distinct()
        available_levels = all_logs.values_list('level', flat=True).distinct()
    except Exception as e:
        available_categories = []
        available_levels = []

    # WebSocket URL for real-time updates
    ws_scheme = 'wss' if request.is_secure() else 'ws'
    ws_url = f"{ws_scheme}://{request.get_host()}/ws/logs/{session_id}/"

    context = {
        'session': session,
        'logs': logs_page,
        'summary_stats': summary_stats,
        'available_categories': available_categories,
        'available_levels': available_levels,
        'current_category_filter': category_filter,
        'current_level_filter': level_filter,
        'current_search': search,
        'realtime_mode': realtime_mode,
        'ws_url': ws_url,
        'page_title': f'Task Details - {session.session_id}',
    }
    
    if not realtime_mode and paginator:
        page_size_options = [25, 50, 100, 200, 500]
        context.update({
            'page_size_options': page_size_options,
            'page_size': per_page if 'per_page' in locals() else 50,
        })
    
    return render(request, 'solicitations/task_details.html', context)

@login_required
@require_http_methods(["GET"])
def get_recent_logs_api(request, session_id):
    """
    API endpoint to get recent logs for real-time mode initialization
    """
    try:
        # Verify session ownership
        session = get_object_or_404(
            RFQScriptSession,
            session_id=session_id,
            user=request.user
        )
        
        # Get recent logs (last 500)
        start_time = session.start_time - timedelta(minutes=1)
        end_time = (session.end_time or timezone.now()) + timedelta(minutes=1)
        
        query_parts = []
        query_parts.append(Q(user=request.user, session_id=session_id))
        
        if hasattr(session, 'task_id') and session.task_id:
            query_parts.append(Q(user=request.user, task_id=session.task_id))
        
        query_parts.append(Q(
            user=request.user,
            timestamp__gte=start_time,
            timestamp__lte=end_time
        ))
        
        final_query = query_parts[0]
        for query_part in query_parts[1:]:
            final_query |= query_part
        
        logs = RFQScriptLog.objects.filter(final_query).select_related('user').distinct().order_by('timestamp', 'id')[:500]
        
        # Serialize logs
        logs_data = []
        for log in logs:
            logs_data.append({
                'id': log.id,
                'timestamp': log.timestamp.isoformat() if log.timestamp else None,
                'level': log.level,
                'category': log.category,
                'message': log.message,
                'cage_code': log.cage_code,
                'rfq_id': log.rfq_id,
                'email_recipient': log.email_recipient,
                'email_subject': log.email_subject,
                'error_details': log.error_details,
                'task_id': log.task_id,
                'session_id': log.session_id,
            })
        
        return JsonResponse({
            'success': True,
            'logs': logs_data,
            'total_count': len(logs_data),
            'session_id': session_id
        })
        
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
####### VIEW TO STOP SENDING RFQS (USER BASIS)  #############

@login_required
@require_POST
def stop_rfq_processing(request):
    """Stop all RFQ processing for the current user and clear all selections"""
    try:
        user = request.user
        data = json.loads(request.body)
        stop_reason = data.get('reason', 'User requested stop')  
        stopped_items = []
        cleared_selections = []
        
        # 1. SET THE STOP FLAG FOR RUNNING SCRIPTS
        try:
            from .models import UserProcessingControl  # Import if you have this model
            control, created = UserProcessingControl.objects.get_or_create(user=user)
            control.request_stop(stop_reason)
        except Exception as e:
            logger.warning(f"Error setting stop flag: {e}")
        
        # 2. STOP QUEUED DJANGO Q TASKS
        try:
            from django_q.models import Task
            all_tasks = Task.objects.filter(
                func__in=[
                    'solicitations.tasks.process_manual_rfq_batch',
                    'solicitations.tasks.process_user_solicitations'
                ],
                stopped__isnull=True,
                started__isnull=True
            )
            
            stopped_task_count = 0
            for task in all_tasks:
                try:
                    if str(user.id) in str(task.args) or user.username in str(task.args):
                        logger.info(f"Stopping task: {task.id} - {task.func}")
                        task.delete()
                        stopped_task_count += 1
                except Exception as e:
                    logger.error(f"Error removing task {task.id}: {e}")
                    
            logger.info(f"Stopped {stopped_task_count} queued tasks")
                    
        except Exception as e:
            stopped_task_count = 0
            logger.error(f"Error stopping tasks: {e}")
        
        # 3. CLEAR PROCESSING SOLICITATIONS (DELETE COMPLETELY)
        try:
            processing_statuses = SolicitationEmailStatus.objects.filter(
                user=user,
                email_status='processing'
            )
            
            processing_count = processing_statuses.count()
            processing_ids = list(processing_statuses.values_list('solicitation_id', flat=True))
            
            if processing_count > 0:
                deleted_count = processing_statuses.delete()
                actual_deleted = deleted_count[0] if isinstance(deleted_count, tuple) else deleted_count
                stopped_items.extend(processing_ids)
                logger.info(f"Cleared {actual_deleted} processing items")
        except Exception as e:
            processing_count = 0
            logger.error(f"Error clearing processing statuses: {e}")
        
        # 4. COMPREHENSIVE USER SELECTION STATE CLEARING
        try:
            # Get the user's selection state
            selection_state = UserSelectionState.objects.filter(user=user).first()
            
            if selection_state:                
                # Store the IDs we're clearing for logging
                old_processing_ids = selection_state.processing_ids or []
                old_selected_ids = selection_state.selected_ids or []
                
                stopped_items.extend(old_processing_ids)
                cleared_selections.extend(old_selected_ids)
                
                # COMPLETELY CLEAR ALL SELECTION STATE
                selection_state.processing_ids = []
                selection_state.selected_ids = []  # Clear selected items
                selection_state.select_all_mode = False  # Disable select all mode
                selection_state.is_submitting = False
                
                # Clear other selection-related fields if they exist
                if hasattr(selection_state, 'selected_solicitation_ids'):
                    selection_state.selected_solicitation_ids = []
                    
                if hasattr(selection_state, 'selected_count'):
                    selection_state.selected_count = 0
                
                if hasattr(selection_state, 'last_action'):
                    selection_state.last_action = 'stopped_and_cleared_by_user'
                
                if hasattr(selection_state, 'action_timestamp'):
                    selection_state.action_timestamp = timezone.now()
                
                # Save the cleared state
                selection_state.save()
                
                logger.info(f"Successfully cleared UserSelectionState for user {user.username}")
                logger.info(f"Cleared {len(old_processing_ids)} processing IDs and {len(old_selected_ids)} selected IDs")
                
            else:
                logger.info(f"No UserSelectionState found for user {user.username}")
                
                # Create a clean state
                UserSelectionState.objects.create(
                    user=user,
                    processing_ids=[],
                    selected_ids=[],
                    select_all_mode=False,
                    is_submitting=False,
                    selected_count=0 if hasattr(UserSelectionState, 'selected_count') else None
                )
                logger.info(f"Created clean UserSelectionState for user {user.username}")
                
        except Exception as e:
            logger.error(f"Error clearing user selection state: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
        
        # 5. FORCE RELEASE REDIS LOCKS
        released_locks = []
        try:
            from .tasks import lock_manager
            for lock_type in ['manual', 'automated', 'large_batch']:
                try:
                    lock_status = lock_manager.check_user_lock_status(user.id, lock_type)
                    if lock_status:
                        released = lock_manager.release_user_lock(user.id, lock_type)
                        if released:
                            released_locks.append(lock_type)
                            logger.info(f"Released {lock_type} lock")
                except Exception as e:
                    logger.error(f"Error releasing {lock_type} lock: {e}")
        except Exception as e:
            logger.error(f"Error accessing lock manager: {e}")
        
        # 6. LOG THE STOP ACTION
        try:
            from .models import RFQScriptLog
            RFQScriptLog.objects.create(
                user=user,
                level='INFO',
                category='processing',
                message=f'RFQ processing stopped by user. Stop flag set, {stopped_task_count} queued tasks removed, {processing_count} processing items cleared, {len(cleared_selections)} selections cleared, UserSelectionState completely reset.',
                extra_data={
                    'stop_reason': stop_reason,
                    'stopped_tasks': stopped_task_count,
                    'processing_items_cleared': processing_count,
                    'selections_cleared': len(cleared_selections),
                    'released_locks': released_locks,
                    'stopped_item_ids': stopped_items[:20],
                    'cleared_selection_ids': cleared_selections[:20],
                    'action': 'stopped_and_cleared_completely',
                    'selection_state_cleared': True,
                    'select_all_mode_disabled': True
                }
            )
        except Exception as e:
            logger.error(f"Error logging stop action: {e}")
        
        # Prepare success message
        message_parts = [
            f"Processing stopped completely",
            f"{stopped_task_count} queued tasks removed" if stopped_task_count > 0 else None,
            f"{processing_count} processing items cleared" if processing_count > 0 else None,
            f"{len(cleared_selections)} selections cleared" if cleared_selections else None,
            "All selections reset"
        ]
        
        success_message = ". ".join(filter(None, message_parts)) + "."
        
        return JsonResponse({
            'success': True,
            'message': success_message,
            'stopped_tasks': stopped_task_count,
            'items_cleared': processing_count,
            'selections_cleared': len(cleared_selections),
            'selection_state_cleared': True,
            'select_all_mode_disabled': True,
            'released_locks': released_locks,
            'stop_flag_set': True,
            'total_items_affected': len(stopped_items),
            'total_selections_cleared': len(cleared_selections)
        })
        
    except Exception as e:
        logger.error(f"Error stopping RFQ processing for user {user.username}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

@login_required
@require_POST
def bulk_delete_reports(request):
    """Delete multiple RFQ task summary reports"""
    try:
        report_ids = request.POST.get('report_ids', '')
        if not report_ids:
            messages.error(request, "No reports selected for deletion.")
            return redirect('solicitations:rfq-reports')
        
        user = request.user
        
        # Handle "select all" case
        if report_ids == 'all':
            # Get all report IDs that the user has access to
            user_reports = RFQTaskSummary.objects.filter(user=user)
            report_id_list = [report.id for report in user_reports]
            
            if not report_id_list:
                messages.warning(request, "No reports found to delete.")
                return redirect('solicitations:rfq-reports')
        else:
            # Parse the comma-separated IDs
            try:
                report_id_list = [int(id.strip()) for id in report_ids.split(',') if id.strip()]
            except ValueError:
                messages.error(request, "Invalid report IDs provided.")
                return redirect('solicitations:rfq-reports')
            
            if not report_id_list:
                messages.error(request, "No valid reports selected for deletion.")
                return redirect('solicitations:rfq-reports')
        
        deleted_count = 0
        deleted_tasks = []
        skipped_count = 0
        
        with transaction.atomic():
            for report_id in report_id_list:
                try:
                    # Get the report
                    report = RFQTaskSummary.objects.get(id=report_id, user=user)
                    
                    # Store task info for logging
                    deleted_tasks.append(report.task_id)
                    
                    # Delete the report
                    report.delete()
                    deleted_count += 1
                    
                except RFQTaskSummary.DoesNotExist:
                    logger.warning(f"Report {report_id} not found during bulk delete")
                    skipped_count += 1
                    continue
                except Exception as e:
                    logger.error(f"Error deleting report {report_id} during bulk delete: {e}")
                    skipped_count += 1
                    continue
        
        # Prepare success/warning messages
        if deleted_count > 0:
            if deleted_count == 1:
                messages.success(request, f"Successfully deleted 1 report.")
            else:
                messages.success(request, f"Successfully deleted {deleted_count} reports.")
            
            logger.info(f"User {user.username} bulk deleted {deleted_count} reports: {deleted_tasks[:10]}")
        
        if skipped_count > 0:
            if deleted_count > 0:
                messages.warning(request, f"Note: {skipped_count} report(s) were skipped (no access or not found).")
            else:
                messages.warning(request, f"No reports were deleted. {skipped_count} report(s) were skipped (no access or not found).")
        
        if deleted_count == 0 and skipped_count == 0:
            messages.warning(request, "No reports were deleted. Please check your selections.")
            
    except Exception as e:
        logger.error(f"Error during bulk delete for user {request.user.username}: {e}")
        messages.error(request, "Error deleting reports. Please try again.")
    
    return redirect('solicitations:rfq-reports')

@login_required
@require_POST
def delete_single_report(request):
    """Delete a single RFQ task summary report"""
    try:
        report_id = request.POST.get('report_id')
        if not report_id:
            messages.error(request, "No report ID provided.")
            return redirect('solicitations:rfq-reports')
        
        user = request.user
        
        try:
            report = RFQTaskSummary.objects.get(id=report_id, user=user)
            task_id = report.task_id
            report.delete()
            
            messages.success(request, f"Successfully deleted report for task {task_id}.")
            logger.info(f"User {user.username} deleted report {report_id} (task {task_id})")
            
        except RFQTaskSummary.DoesNotExist:
            messages.error(request, "Report not found or you don't have permission to delete it.")
        except Exception as e:
            logger.error(f"Error deleting single report {report_id}: {e}")
            messages.error(request, "Error deleting report. Please try again.")
            
    except Exception as e:
        logger.error(f"Error in delete_single_report: {e}")
        messages.error(request, "Error deleting report. Please try again.")
    
    return redirect('solicitations:rfq-reports')

@login_required
@require_POST
def bulk_delete_tasks(request):
    """Delete multiple RFQ processing tasks and their logs"""
    try:
        task_ids = request.POST.get('task_ids', '')
        if not task_ids:
            messages.error(request, "No tasks selected for deletion.")
            return redirect('solicitations:user-tasks-list')  # Fixed URL name
        
        user = request.user
        
        # Handle "select all" case
        if task_ids == 'all':
            # Get all session_ids that the user has access to
            user_sessions = RFQScriptSession.objects.filter(user=user)
            task_id_list = [session.session_id for session in user_sessions]  # Use session_id
            
            if not task_id_list:
                messages.warning(request, "No tasks found to delete.")
                return redirect('solicitations:user-tasks-list')  # Fixed URL name
        else:
            # Parse the comma-separated session_ids (they're strings, not integers)
            try:
                task_id_list = [id.strip() for id in task_ids.split(',') if id.strip()]
            except ValueError:
                messages.error(request, "Invalid task IDs provided.")
                return redirect('solicitations:user-tasks-list')  # Fixed URL name
            
            if not task_id_list:
                messages.error(request, "No valid tasks selected for deletion.")
                return redirect('solicitations:user-tasks-list')  # Fixed URL name
        
        deleted_count = 0
        deleted_sessions = []
        skipped_count = 0
        
        with transaction.atomic():
            for task_id in task_id_list:
                try:
                    # Get the session using session_id as primary key
                    session = RFQScriptSession.objects.get(session_id=task_id, user=user)
                    
                    # Store session info for logging
                    deleted_sessions.append(session.session_id)
                    
                    # Delete associated logs first
                    RFQScriptLog.objects.filter(
                        user=user,
                        session_id=session.session_id
                    ).delete()
                    
                    # Delete the session
                    session.delete()
                    deleted_count += 1
                    
                except RFQScriptSession.DoesNotExist:
                    logger.warning(f"Task {task_id} not found during bulk delete")
                    skipped_count += 1
                    continue
                except Exception as e:
                    logger.error(f"Error deleting task {task_id} during bulk delete: {e}")
                    skipped_count += 1
                    continue
        
        # Prepare success/warning messages
        if deleted_count > 0:
            if deleted_count == 1:
                messages.success(request, f"Successfully deleted 1 task and its logs.")
            else:
                messages.success(request, f"Successfully deleted {deleted_count} tasks and their logs.")
            
            logger.info(f"User {user.username} bulk deleted {deleted_count} tasks: {deleted_sessions[:10]}")
        
        if skipped_count > 0:
            if deleted_count > 0:
                messages.warning(request, f"Note: {skipped_count} task(s) were skipped (no access or not found).")
            else:
                messages.warning(request, f"No tasks were deleted. {skipped_count} task(s) were skipped (no access or not found).")
        
        if deleted_count == 0 and skipped_count == 0:
            messages.warning(request, "No tasks were deleted. Please check your selections.")
            
    except Exception as e:
        logger.error(f"Error during bulk delete for user {request.user.username}: {e}")
        messages.error(request, "Error deleting tasks. Please try again.")
    
    return redirect('solicitations:user-tasks-list')  # Fixed URL name

@login_required
@require_POST
def delete_single_task(request):
    """Delete a single RFQ processing task and its logs"""
    try:
        task_id = request.POST.get('task_id')
        if not task_id:
            messages.error(request, "No task ID provided.")
            return redirect('solicitations:user-tasks-list')  # Fixed URL name
        
        user = request.user
        
        try:
            # Get session using session_id as primary key
            session = RFQScriptSession.objects.get(session_id=task_id, user=user)
            session_id = session.session_id
            
            # Delete associated logs first
            logs_deleted = RFQScriptLog.objects.filter(
                user=user,
                session_id=session.session_id
            ).delete()
            
            # Delete the session
            session.delete()
            
            messages.success(request, f"Successfully deleted task {session_id[:12]}... and {logs_deleted[0] if logs_deleted else 0} associated logs.")
            logger.info(f"User {user.username} deleted task {task_id} (session {session_id})")
            
        except RFQScriptSession.DoesNotExist:
            messages.error(request, "Task not found or you don't have permission to delete it.")
        except Exception as e:
            logger.error(f"Error deleting single task {task_id}: {e}")
            messages.error(request, "Error deleting task. Please try again.")
            
    except Exception as e:
        logger.error(f"Error in delete_single_task: {e}")
        messages.error(request, "Error deleting task. Please try again.")
    
    return redirect('solicitations:user-tasks-list')  # Fixed URL name    
    return redirect('solicitations:user-tasks-list')

