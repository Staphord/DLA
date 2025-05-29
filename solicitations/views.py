import json
import os
from django.core.mail import send_mail
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponseForbidden, HttpResponseNotFound, JsonResponse
from accounts.models import CustomUser, Invitation, VerificationToken
from . models import RFQ, EmailSettings, MailTemplate, OEMUser, RFQChat, RFQChatMessage, RFQItem, RFQItemReply, RFQReply, Solicitation,OEM,GitHubWorkflow, SolicitationEmailStatus, UserOEMCustomization
from django.contrib import messages
import subprocess
from . forms import EmailSettingsForm, LogoUpdateForm, RFQItemReplyForm, UserOEMCustomizationForm, UserRegistrationForm,RFQReplyForm,GitHubWorkflowForm, UserUpdateForm
from django.core.paginator import Paginator
from django.db.models import Q
from django.template.loader import render_to_string
import pandas as pd
from django.urls import reverse
from datetime import datetime,timedelta,date
from django.utils import timezone
from git import Repo
from ruamel.yaml import YAML
from django.db.models import Sum
from django.core.signing import Signer
import base64
import traceback
from accounts.views import register_with_invitation


## path to yaml file
WORKFLOW_FILE_PATH = r"C:\Users\Staphord Bengesi\Desktop\DLA\.github\workflows\extract_data.yml"


def base(request):
    ## replied rfq
    replied_rfq = RFQReply.objects.filter(rfq_creator = request.user, is_viewed = False)

    ## pass data to the template
    context = {
        'replied_rfq':replied_rfq
        }
    return render(request,'solicitations/base.html',context)

def home(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            selected_date = data.get('selected_date')
            is_user_input = data.get('is_user_input', False)
            
            # Store both the date and whether it was user input
            request.session['selected_date'] = selected_date
            request.session['is_user_input'] = is_user_input
            
            return JsonResponse({'status': 'success'})
        except json.JSONDecodeError:
            return JsonResponse({'status': 'error', 'message': 'Invalid JSON'})

    user = request.user
    today = datetime.today().strftime("%m-%d-%Y")
    
    # Get the selected_date from session or use today's date
    selected_date = request.session.get('selected_date', today)
    
    # Fetch all normal users
    clients = CustomUser.objects.exclude(is_superuser=True)\
                               .filter(user_type='client')\
                               .exclude(Q(first_name='') | Q(first_name=None) | Q(last_name='') | Q(last_name=None))
    total_clients = clients.count()
    
    # Fetch all solicitations
    solicitations = Solicitation.objects.all().exclude(Q(cage='-') | Q(cage='N/A')).filter(return_by_date__gte=today)
    total_solicitations = solicitations.filter(return_by_date__gte=selected_date).count()
    
    # Fetch user rfqs
    sent_rfqs = RFQ.objects.filter(created_by=request.user)
    total_sent_rfqs = sent_rfqs.count()
    
    # Replied rfq
    replied_rfq = RFQReply.objects.filter(rfq_creator=request.user, is_viewed=False)
    
    context = {
        'total_clients': total_clients,
        'total_solicitations': total_solicitations,
        'sent_rfqs': sent_rfqs,
        'total_sent_rfqs': total_sent_rfqs,
        'replied_rfq': replied_rfq,
        'selected_date': selected_date,
        'is_user_input': request.session.get('is_user_input', False)
    }
    
    return render(request, 'solicitations/home.html', context)

## view to show all solicitations
def solicitations(request):
    # Get current date as date object (not string)
    today = timezone.now().date()
    
    # Calculate cutoff date (7 days ago)
    cutoff_date = today - timedelta(days=7)
    
    # Get all sent statuses for this user
    sent_statuses = SolicitationEmailStatus.objects.filter(
        user=request.user,
        email_status='sent'
    ).values_list('solicitation_id', flat=True)
    
    # Get all solicitations that meet our criteria
    solicitations = Solicitation.objects.exclude(
        Q(cage='-') | Q(cage='N/A') | Q(id__in=sent_statuses)
    ).filter(
        scraped_date__gte=cutoff_date    # Recent scrapes
    ).order_by('-scraped_date')          # Newest first
    
    # Filter for non-expired solicitations
    valid_solicitations = []
    for solicitation in solicitations:
        try:
            # Parse return_by_date (assuming format mm-dd-yyyy)
            return_date = datetime.strptime(solicitation.return_by_date, "%m-%d-%Y").date()
            if return_date >= today:
                valid_solicitations.append(solicitation)
        except (ValueError, AttributeError):
            # Skip if date format is invalid
            continue
    
    # Add OEM disabled status for each valid solicitation
    for solicitation in valid_solicitations:
        oem = OEM.objects.filter(cage=solicitation.cage).first()
        solicitation.oem_disabled = OEMUser.objects.filter(
            oem=oem, 
            user=request.user, 
            is_disabled=True
        ).exists() if oem else False
    
    # Pagination - 50 items per page
    paginator = Paginator(valid_solicitations, 5)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Get email settings
    try:
        email_settings = EmailSettings.objects.get(user=request.user)
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
        'total_solicitations': len(valid_solicitations),  # Total count
        'replied_rfq': RFQReply.objects.filter(rfq_creator=request.user, is_viewed=False),
        'auto_send': auto_send,
        'send_day_display': send_day_display,
        'send_time_display': send_time_display,
        'cutoff_date': cutoff_date.strftime("%Y-%m-%d")
    }
    
    return render(request, 'solicitations/solicitations.html', context)



## view to show solicitation detail
def solicitation_detail(request,solicitation):
    solicitation_detail = Solicitation.objects.get(pk=solicitation)
    ## replied rfq
    replied_rfq = RFQReply.objects.filter(rfq_creator = request.user, is_viewed = False)
    context = {"solicitation_detail":solicitation_detail,'replied_rfq':replied_rfq}
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


def scrap_solicitations(request):
    if request.method == "POST" and request.headers.get("X-Requested-With") == "XMLHttpRequest":
        try:
            # Parse the JSON data from the request body, or use an empty dict if the body is empty
            data = json.loads(request.body) if request.body else {}
            scrape_date = data.get('date')  # Get the date from the request body
            

            # Use the provided scrape_date or a default value
            if scrape_date:
                formated_date = datetime.strptime(scrape_date, "%Y-%m-%d").strftime("%m-%d-%Y")
                print(f"Scraping for date: {scrape_date}")
            else:
                formated_date = datetime.now().strftime("%m-%d-%Y")  # Default to the current date
                print("No scrape date provided. Defaulting to current date.")

            # Path to the Python executable and script
            python_exec = r"C:\Users\Staphord Bengesi\Desktop\DLA\venv\Scripts\python.exe"
            script_path = os.path.join(os.getcwd(), "extractSolicitations.py")

            # Run the external Python script, passing the user ID and date as arguments
            result = subprocess.Popen(
                [python_exec, script_path, str(formated_date)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Log output line by line
            for line in iter(result.stdout.readline, ''):
                print(line.strip())

            # Wait for the script to finish
            stdout, stderr = result.communicate()

            if result.returncode != 0:
                error_message = f"Subprocess failed with error: {stderr}"
                print(error_message)  # Log the error for debugging
                return JsonResponse({"error": error_message}, status=500)

            # Return success after script completes
            return JsonResponse({"success": "Completed"})

        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON in request body"}, status=400)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
    else:
        return JsonResponse({"error": "Invalid request method or headers"}, status=400)

def searched_solicitations(request):
    if request.method == "POST":
        mysearch = request.POST.get('mysearch', '') 
        if mysearch:
            data = Solicitation.objects.filter(
                Q(cage__icontains=mysearch) | Q(NSN__icontains=mysearch) | Q(quantity__icontains=mysearch) | Q(nomenclature__icontains=mysearch)
            )

            context = {'mysearch': mysearch, 'data': data}
            return render(request, 'solicitations/searched_solicitations.html', context)
        else:
            # Handle empty search term
            context = {'mysearch': '', 'data': Solicitation.objects.none()}
            return render(request, 'solicitations/searched_solicitations.html', context)
    else:
        # Handle GET request
        context = {'mysearch': '', 'data': Solicitation.objects.none()}
        return render(request, 'solicitations/searched_solicitations.html', context)
    
def filtered_solicitations(request):
    solicitations = Solicitation.objects.all()  # Default queryset

    if request.method == 'POST':
        # Get input dates from POST data
        issued_date_from = request.POST.get('issued_date_from')
        issued_date_to = request.POST.get('issued_date_to')
        return_by_date_from = request.POST.get('return_by_date_from')
        return_by_date_to = request.POST.get('return_by_date_to')

        # Filter by issued date range
        if issued_date_from and issued_date_to:
            # Convert input dates (YYYY-MM-DD) to database format (MM-DD-YYYY)
            issued_date_from_obj = datetime.strptime(issued_date_from, '%Y-%m-%d')
            issued_date_from_str = issued_date_from_obj.strftime('%m-%d-%Y')
            issued_date_to_obj = datetime.strptime(issued_date_to, '%Y-%m-%d')
            issued_date_to_str = issued_date_to_obj.strftime('%m-%d-%Y')

            # Filter using the formatted dates
            solicitations = solicitations.filter(issued_date__range=(issued_date_from_str, issued_date_to_str))

        # Filter by return by date range
        if return_by_date_from and return_by_date_to:
            # Convert input dates (YYYY-MM-DD) to database format (MM-DD-YYYY)
            return_by_date_from_obj = datetime.strptime(return_by_date_from, '%Y-%m-%d')
            return_by_date_from_str = return_by_date_from_obj.strftime('%m-%d-%Y')
            return_by_date_to_obj = datetime.strptime(return_by_date_to, '%Y-%m-%d')
            return_by_date_to_str = return_by_date_to_obj.strftime('%m-%d-%Y')

            # Filter using the formatted dates
            solicitations = solicitations.filter(return_by_date__range=(return_by_date_from_str, return_by_date_to_str))

    # Render the filtered solicitations
    return render(request, 'solicitations/filtered_solicitations.html', {'solicitations': solicitations})

def email_settings(request):
    """View for managing email automation settings"""
    # Get or create settings for the current user
    settings, created = EmailSettings.objects.get_or_create(user=request.user)
    
    if request.method == 'POST':
        # Process the form data
        form = EmailSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            # Check which action was performed
            action_type = request.POST.get('action_type', 'toggle_status')
            
            if action_type == 'save_schedule':
                # Save the schedule changes and ensure auto_send is enabled
                settings = form.save(commit=False)
                settings.auto_send = True  # Automatically enable when saving changes
                settings.save()
                
                # Include schedule details in message
                day_display = dict(EmailSettings.DAY_CHOICES)[settings.send_day]
                time_display = settings.send_time.strftime('%I:%M %p')
                messages.success(request, f"Schedule updated and automation enabled ({day_display} at {time_display})")
            
            elif action_type == 'toggle_status':
                # Toggle the auto_send status (opposite of current)
                settings = form.save(commit=False)
                settings.auto_send = not settings.auto_send
                settings.save()
                
                # Create appropriate message
                status_msg = "enabled" if settings.auto_send else "disabled"
                
                if settings.auto_send:
                    # Include schedule details in message only when enabling
                    day_display = dict(EmailSettings.DAY_CHOICES)[settings.send_day]
                    time_display = settings.send_time.strftime('%I:%M %p')
                    schedule_info = f" ({day_display} at {time_display})"
                    messages.success(request, f"Email automation has been {status_msg}{schedule_info}")
                else:
                    messages.success(request, f"Email automation has been {status_msg}")
            
            return redirect('solicitations:solicitations')
    else:
        form = EmailSettingsForm(instance=settings)
    
    context = {
        'form': form,
        'is_enabled': settings.auto_send,
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
    
    # Get replied RFQs
    replied_rfq = RFQReply.objects.filter(rfq_creator=request.user, is_viewed=False)
    
    context = {
        "clients": clients,
        'total_clients': total_clients,
        'replied_rfq': replied_rfq
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
    ## replied rfq
    replied_rfq = RFQReply.objects.filter(rfq_creator = request.user, is_viewed = False)

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
        'form': form,'replied_rfq':replied_rfq
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

    # Fetch all RFQ replies, ordered by the latest first
    replied_rfq_queryset = RFQReply.objects.filter(rfq__created_by=request.user).order_by('-id')
    replied_rfq_queryse = RFQReply.objects.filter(rfq__created_by=request.user).count()

    # Count all RFQs (total number of replies)
    total_replied_rfq = replied_rfq_queryset.filter(rfq__created_by=request.user).count()
    ## replied rfq
    replied_rfq = RFQReply.objects.filter(rfq_creator = request.user, is_viewed = False)
    context = {'sent_rfqs':sent_rfqs,'total_sent_rfqs':total_sent_rfqs,'rfq':rfq,'total_replied_rfq':total_replied_rfq,
               'replied_rfq_queryse':replied_rfq_queryse,'replied_rfq':replied_rfq}
    return render(request,'solicitations/procurements/sent_rfq.html',context)


#view to search for sent RFQS
def search_sent_rfq(request):
    if request.method == "POST":
        searched = request.POST['search-sent']

        rfqId = RFQ.objects.filter(Q(unique_id__contains = searched) & Q(created_by = request.user))

        
        sent_rfqs = RFQ.objects.filter(created_by=request.user)
        # count all rfqs
        total_sent_rfqs = sent_rfqs.filter(created_by=request.user).count()

        # Fetch all RFQ replies, ordered by the latest first
        replied_rfq_queryset = RFQReply.objects.filter(rfq__created_by=request.user).order_by('-id')

        # Count all RFQs (total number of replies)
        total_replied_rfq = replied_rfq_queryset.filter(rfq__created_by=request.user).count()

        context ={'searched':searched, 'rfqId':rfqId,'total_sent_rfqs':total_sent_rfqs,'total_replied_rfq':total_replied_rfq}
        return render(request,'solicitations/procurements/searched_sent.html',context)
    else:
        return render(request,'solicitations/procurements/sent_rfq.html')

## View to show RFQ detail
def rfq_detail(request, rfq):
    try:
        rfq = RFQ.objects.get(pk=rfq)
    except RFQ.DoesNotExist:
        return HttpResponseNotFound("RFQ not found")
    
    # Check if this is a consolidated RFQ (has multiple items)
    rfq_items = RFQItem.objects.filter(rfq=rfq)
    is_consolidated = rfq_items.exists()
    
    # Get all solicitations for a consolidated RFQ, making sure to not include duplicates
    if is_consolidated:
        # Get all solicitations including the primary one
        all_solicitations = [item.solicitation for item in rfq_items]
        
        # Count the total number of unique solicitations
        total_item_count = len(set(sol.id for sol in all_solicitations))
    else:
        all_solicitations = []
        total_item_count = 1  # Just the primary solicitation
    
    # Get replied RFQs
    replied_rfq = RFQReply.objects.filter(rfq_creator=request.user, is_viewed=False)
    
    context = {
        'rfq': rfq,
        'replied_rfq': replied_rfq,
        'is_consolidated': is_consolidated,
        'all_solicitations': all_solicitations,
        'total_item_count': total_item_count
    }
    
    return render(request, 'solicitations/procurements/rfq_detail.html', context)

##view to delete RFQ
def delete_rfq(request,rfq):
    delete_rfq = RFQ.objects.get(pk=rfq)
    delete_rfq.delete()
    return redirect('solicitations:sent-rfq')

## this is for displaying form for reply
def rfq_reply_view(request):
    rfq_unique_id = request.GET.get('rfq_unique_id')
    item_index = request.GET.get('item_index', '0')
    
    try:
        item_index = int(item_index)
    except ValueError:
        item_index = 0
        
    rfq = get_object_or_404(RFQ, unique_id=rfq_unique_id)
    rfq_creator = rfq.created_by  # The user who created the RFQ
    
    # Get all solicitations
    all_solicitations = [rfq.solicitation]  # Start with primary
    rfq_items = RFQItem.objects.filter(rfq=rfq)
    is_consolidated = rfq_items.exists()
    
    if is_consolidated:
        for item in rfq_items:
            if item.solicitation.id != rfq.solicitation.id:
                all_solicitations.append(item.solicitation)
    
    # Get current solicitation
    if 0 <= item_index < len(all_solicitations):
        current_solicitation = all_solicitations[item_index]
    else:
        current_solicitation = rfq.solicitation
        item_index = 0
    
    # Check if already replied to THIS SPECIFIC ITEM
    existing_reply = RFQItemReply.objects.filter(
        rfq=rfq, 
        rfq_creator=rfq_creator,  # Use the RFQ creator, not request.user
        solicitation=current_solicitation
    ).first()
    
    # Determine if this is the last item
    is_last_item = item_index == len(all_solicitations) - 1
    
    form = RFQReplyForm()  # Using RFQReplyForm here
    
    if request.method == 'POST':
        form = RFQReplyForm(request.POST, request.FILES)  # Using RFQReplyForm here
        if form.is_valid():
            # Create RFQItemReply
            rfq_item_reply = RFQItemReply(
                rfq=rfq,
                solicitation=current_solicitation,
                rfq_creator=rfq_creator,  # Use the RFQ creator, not request.user
                price=form.cleaned_data.get('price')
            )
            
            # Only process document, note, and delivery mode if this is the last item or not consolidated
            if not is_consolidated or is_last_item:
                rfq_item_reply.document = form.cleaned_data.get('document')
                rfq_item_reply.short_note = form.cleaned_data.get('short_note')
                rfq_item_reply.delivery_mode = form.cleaned_data.get('delivery_mode')
            else:
                rfq_item_reply.document = None
                rfq_item_reply.short_note = ""
                rfq_item_reply.delivery_mode = "Free"
                
            rfq_item_reply.save()
            
            # If this is the last item or only item, create/update the main RFQReply
            if not is_consolidated or is_last_item:
                # Calculate total price
                total_price = 0
                if is_consolidated:
                    # Sum prices from all item replies
                    from django.db.models import Sum
                    total_price = RFQItemReply.objects.filter(
                        rfq=rfq, rfq_creator=rfq_creator  # Use rfq_creator here
                    ).aggregate(Sum('price'))['price__sum'] or 0
                else:
                    total_price = rfq_item_reply.price
                
                # Get or create the main RFQReply
                main_reply, created = RFQReply.objects.get_or_create(
                    rfq=rfq,
                    rfq_creator=rfq_creator,  # Use rfq_creator here
                    defaults={
                        'price': total_price,
                        'delivery_mode': rfq_item_reply.delivery_mode,
                        'short_note': rfq_item_reply.short_note,
                        'document': rfq_item_reply.document
                    }
                )
                
                # If not created (already exists), update it
                if not created:
                    main_reply.price = total_price
                    main_reply.delivery_mode = rfq_item_reply.delivery_mode
                    main_reply.short_note = rfq_item_reply.short_note
                    if rfq_item_reply.document:
                        main_reply.document = rfq_item_reply.document
                    main_reply.save()
            
            # Redirect to next item if available
            if is_consolidated and not is_last_item:
                next_index = item_index + 1
                return JsonResponse({
                    "success": True, 
                    "next_item": True,
                    "next_url": f"?rfq_unique_id={rfq_unique_id}&item_index={next_index}"
                })
            else:
                return JsonResponse({"success": True, "next_item": False})
    
    return render(request, 'solicitations/procurements/rfq_reply.html', {
        'form': form,
        'rfq': rfq,
        'current_solicitation': current_solicitation,
        'is_consolidated': is_consolidated,
        'item_index': item_index,
        'total_items': len(all_solicitations),
        'existing_reply': existing_reply,
        'is_last_item': is_last_item,
        'all_solicitations': all_solicitations
    })

## view to show all replied views
def replied_rfq(request):
    # Fetch all standard RFQ replies
    replied_rfq_queryset = RFQReply.objects.filter(rfq__created_by=request.user).order_by('-id')
    
    # Fetch all individual item replies and get their unique RFQ IDs
    item_replies = RFQItemReply.objects.filter(rfq__created_by=request.user)
    
    # Get RFQ IDs that have item replies but no standard reply
    rfq_ids_with_item_replies = item_replies.values_list('rfq', flat=True).distinct()
    
    # Check which RFQs have item replies but no standard reply
    for rfq_id in rfq_ids_with_item_replies:
        if not replied_rfq_queryset.filter(rfq_id=rfq_id).exists():
            # Get the RFQ object
            rfq = RFQ.objects.get(id=rfq_id)
            
            # Count how many item replies this RFQ has
            item_count = RFQItemReply.objects.filter(rfq=rfq, rfq_creator=request.user).count()
            
            # Set appropriate note based on item count
            if item_count > 1:
                note = f'Consolidated reply for {item_count} items'
                delivery_mode = 'Mixed'
            else:
                # Get the single item reply
                item_reply = RFQItemReply.objects.filter(rfq=rfq, rfq_creator=request.user).first()
                if item_reply:
                    note = f'Reply for {item_reply.solicitation.nomenclature}'
                    delivery_mode = item_reply.delivery_mode
                else:
                    note = 'Standard reply'
                    delivery_mode = 'Standard'
            
            # Calculate total price from item replies
            total_price = RFQItemReply.objects.filter(rfq=rfq, rfq_creator=request.user).aggregate(Sum('price'))['price__sum'] or 0
            
            # Create and save a real RFQReply object
            RFQReply.objects.create(
                rfq=rfq,
                rfq_creator=request.user,
                price=total_price,
                delivery_mode=delivery_mode,
                short_note=note,
                is_viewed=False
            )
    
    # After creating any missing records, fetch the complete list again
    replied_rfq_queryset = RFQReply.objects.filter(rfq__created_by=request.user).order_by('-id')
    
    # Count all RFQs (total number of replies)
    total_replied_rfq = replied_rfq_queryset.count()
    
    # Set up the paginator, 25 replies per page
    paginator = Paginator(replied_rfq_queryset, 25)
    page = request.GET.get('page')
    # Get the current page of replies
    rfq = paginator.get_page(page)
    
    # Fetch all RFQs
    sent_rfqs = RFQ.objects.filter(created_by=request.user)
    # Count all RFQs
    total_sent_rfqs = sent_rfqs.filter(created_by=request.user).count()
    
    ## unviewed replies
    replied_rfq = RFQReply.objects.filter(rfq_creator=request.user, is_viewed=False)
    
    context = {
        'total_replied_rfq': total_replied_rfq,
        'rfq': rfq,
        'total_sent_rfqs': total_sent_rfqs,
        'replied_rfq': replied_rfq
    }
    return render(request, 'solicitations/procurements/replied_rfq.html', context)


## View to show Replied RFQ detail
def replied_rfq_detail(request, rfq):
    # Retrieve the RFQReply object or return a 404 error if it doesn't exist
    rfq_instance = get_object_or_404(RFQReply, pk=rfq)
    
    # Get all related RFQItemReply objects for this RFQ
    rfq_item_replies = RFQItemReply.objects.filter(rfq=rfq_instance.rfq)
    
    # Check if this RFQ has multiple item replies (consolidated)
    is_consolidated = rfq_item_replies.count() > 1
    
    # Calculate the total price (sum of price × quantity for each item)
    total_price = 0
    for item in rfq_item_replies:
        try:
            # Convert quantity to float (since it's stored as a string)
            quantity = float(item.solicitation.quantity)
            # Calculate item total and add to running sum
            item_total = float(item.price) * quantity
            total_price += item_total
        except (ValueError, TypeError):
            # Skip items where conversion fails
            print(f"Warning: Could not calculate total for item {item.id}")
    
    # Format total price to 2 decimal places
    total_price = round(total_price, 2)
    
    # Toggle the is_viewed field to True
    if not rfq_instance.is_viewed:
        rfq_instance.is_viewed = True
        rfq_instance.save()
        
        # Also mark any related item replies as viewed
        if rfq_item_replies.exists():
            rfq_item_replies.update(is_viewed=True)
    
    # Check if a chat exists for this RFQ
    chat_exists = hasattr(rfq_instance.rfq, 'chat')
    
    # Pass the RFQReply object to the template
    context = {
        'rfq': rfq_instance,
        'replied_rfq': RFQReply.objects.filter(rfq_creator=request.user, is_viewed=False),
        'is_consolidated': is_consolidated,
        'rfq_item_replies': rfq_item_replies,
        'calculated_total': total_price,
        'chat_exists': chat_exists
    }
    
    return render(request, 'solicitations/procurements/replied_rfq_detail.html', context)

#view to search for Replied RFQS
def search_replied_rfq(request):
    if request.method == "POST":
        searched = request.POST['search-replied']
        
        replied_rfq_queryset = RFQReply.objects.filter(
                Q(rfq__unique_id__icontains=searched) & 
                Q(rfq_creator=request.user)
            ).order_by('-id')

        # Count all Replied RFQs
        total_replied_rfq = RFQReply.objects.filter(rfq_creator=request.user).count()

        # Fetch Sent RFQs
        sent_rfqs = RFQ.objects.filter(created_by=request.user)

        # Count all Sent RFQs
        total_sent_rfqs = sent_rfqs.count()
        ## replied rfq
        replied_rfq = RFQReply.objects.filter(rfq_creator = request.user, is_viewed = False)

        context = {
            'searched': searched, 
            'replied_rfq_queryset': replied_rfq_queryset,
            'total_replied_rfq': total_replied_rfq,
            'sent_rfqs': sent_rfqs,
            'total_sent_rfqs': total_sent_rfqs,
            'replied_rfq':replied_rfq
        }
        return render(request, 'solicitations/procurements/searched_replied.html', context)
    else:
        return render(request, 'solicitations/procurements/replied_rfq.html')

##view to delete Replied RFQ
def delete_replied_rfq(request,rfq):
    delete_replied_rfq = RFQReply.objects.get(pk=rfq)
    delete_replied_rfq.delete()
    return redirect('solicitations:replied-rfq')

## view to send RFQS
def send_rfqs(request):
    try:
        data = json.loads(request.body)
        selected_ids = data.get("selected_ids", [])

        if not selected_ids:
            return JsonResponse({"error": "No solicitations selected"}, status=400)

        # Get solicitations and verify they exist
        solicitations = Solicitation.objects.filter(id__in=selected_ids)
        if not solicitations.exists():
            return JsonResponse({"error": "No matching solicitations found"}, status=404)

        # Serialize data
        solicitation_data = []
        for sol in solicitations:
            # Create or update email status
            status, created = SolicitationEmailStatus.objects.get_or_create(
                solicitation=sol,
                user=request.user,
                defaults={'email_status': 'processing'}
            )
            
            solicitation_data.append({
                "id": sol.id,
                "cage": sol.cage,
                "nomenclature": sol.nomenclature,
                "quantity": sol.quantity,
                "return_by_date": sol.return_by_date,
                "NSN": sol.NSN,
            })

        # Get mail template and user data
        mail_template, created = MailTemplate.objects.get_or_create(userMail=request.user)
        mail_data = {
            "salutation": mail_template.salutation,
            "heading": mail_template.heading,
            "body": mail_template.body,
        }

        user_data = {
            "username": request.user.username,
            "email": request.user.email,
            "phone": getattr(request.user, "phone", None),
            "address": getattr(request.user, "address", None),
            "companyName": getattr(request.user, "companyName", None),
            "logo": request.user.logo.url if hasattr(request.user, "logo") and request.user.logo else None,
        }

        combined_data = {
            "user_data": user_data,
            "mail_data": mail_data,
            "solicitations": solicitation_data,
        }

        # Run external script
        python_exec = r"C:\Users\Staphord Bengesi\Desktop\DLA\venv\Scripts\python.exe"
        script_path = os.path.join(os.getcwd(), "infoExtractorSendRfq.py")

        result = subprocess.Popen(
            [python_exec, script_path, json.dumps(combined_data)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        stdout, stderr = result.communicate()

        if result.returncode != 0:
            error_message = f"Subprocess failed with error: {stderr}"
            print(error_message)
            
            # Update status to failed
            for sol in solicitations:
                status = SolicitationEmailStatus.objects.get(
                    solicitation=sol,
                    user=request.user
                )
                status.email_status = 'failed'
                status.save()
                
            return JsonResponse({"error": error_message}, status=500)

        # If successful, update status to sent
        for sol in solicitations:
            status = SolicitationEmailStatus.objects.get(
                solicitation=sol,
                user=request.user
            )
            status.email_status = 'sent'
            status.email_sent = True
            status.email_sent_at = timezone.now()
            status.save()

        return JsonResponse({
            "message": stdout, 
            "data": solicitation_data
        }, status=200)

    except Exception as e:
        error_message = f"Unexpected error: {str(e)}"
        print(error_message)
        return JsonResponse({"error": error_message}, status=500)

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
    
    # Dynamic calculation for "Replied" - count of replies for all RFQs
    replied = RFQReply.objects.filter(rfq_creator=request.user).count() 
    print(f'REPLIED RFQS {replied}')
    
    # Dynamic calculation for "Sent" - count of all RFQs
    sent = RFQ.objects.filter(created_by=request.user).count()
    
    # Return the data as JSON
    return JsonResponse({
        'solicitations': solicitations,
        'replied': replied,
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
    user = request.user  # Assuming the user is authenticated
    mail_template = MailTemplate.objects.filter(userMail=user).first()

    # Safeguard for optional fields in CustomUser
    company_name = getattr(user, 'companyName', "Your Company Name")
    address = getattr(user, 'address', "Your Address")
    logo_url = user.logo.url if hasattr(user, 'logo') and user.logo else None
    phone = getattr(user, 'phone', "Not Provided")

    # Prepare the response data
    data = {
        "salutation": mail_template.salutation if mail_template else "Dear Mr/Ms",
        "heading": mail_template.heading if mail_template else "REQUEST FOR QUOTATION",
        "body": mail_template.body if mail_template else "I hope this message finds you well. We are currently looking for the following item. Kindly provide your lowest possible price.",
        'company': company_name,
        'address': address,
        'logo': logo_url,  # URL or None if no logo exists
        "phone": phone,
    }

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
    # Filter OEMs related to the user and are not disabled for that user
    oems = OEM.objects.filter(oemuser__user=request.user, oemuser__is_disabled=False)
    #print(oems)

    # Filter OEMs related to the user and are disabled for that user
    disabled_oems = OEM.objects.filter(oemuser__user=request.user, oemuser__is_disabled=True)
    #print(disabled_oems)

    p = Paginator(oems.order_by('-id'),25)
    page = request.GET.get('page')
    oem = p.get_page(page)

    # Count total OEMs for the user that are not disabled
    total_oems = oems.count()

    ## replied rfq
    replied_rfq = RFQReply.objects.filter(rfq_creator = request.user, is_viewed = False)

    # Context to pass to the template
    context = {
        'oems': oems,
        'oem':oem,
        'total_oems': total_oems,
        'disabled_oems': disabled_oems,'replied_rfq':replied_rfq
    }
    return render(request, 'solicitations/oems/active_oems.html', context)


## view to show oem detail page
def oem_detail(request, oem):
    # Fetch the specific OEM object using the primary key
    oem_obj = get_object_or_404(OEM, pk=oem)
    
    # Get all OEMUser associations for this OEM
    oem_users = OEMUser.objects.filter(oem=oem_obj)
    
    # Get replied RFQs
    replied_rfq = RFQReply.objects.filter(rfq_creator=request.user, is_viewed=False)
    
    # Get the user's customization for this OEM if it exists
    try:
        customization = UserOEMCustomization.objects.get(user=request.user, oem=oem_obj)
        
        # Create a dictionary with OEM data, overriding with customizations where available
        oem_data = {
            'name': customization.custom_name or oem_obj.name,
            'cage': oem_obj.cage,  
            'email': customization.custom_email or oem_obj.email,
            'phone': customization.custom_phone or oem_obj.phone,
            'fax': customization.custom_fax or oem_obj.fax,
            'city': customization.custom_city or oem_obj.city,
            'street': customization.custom_street or oem_obj.street,
            'postal_code': customization.custom_postal_code or oem_obj.postal_code,
        }
    except UserOEMCustomization.DoesNotExist:
        # If no customization exists, use original OEM data
        oem_data = None  
    
    # Pass the data to the template
    context = {
        'oem': oem_obj, 
        'oem_data': oem_data,
        'oem_users': oem_users,
        'replied_rfq': replied_rfq
    }
    
    return render(request, 'solicitations/oems/oem_detail.html', context)

## view to search for OEM
def search_oem(request):
    if request.method == "POST":
        searched = request.POST['search-oem']
        oem = OEM.objects.filter(cage__icontains = searched).first()

        ## replied rfq
        replied_rfq = RFQReply.objects.filter(rfq_creator = request.user, is_viewed = False)
        context = {'searched': searched,'oem':oem,'replied_rfq':replied_rfq}
        return render(request,'solicitations/oems/searched_oem.html',context)
    else:
        return render(request,'solicitations/oems/all_oems.html')
    
## view to show all disabled oems
def disabled_oems(request):
    oems = OEM.objects.filter(oemuser__user=request.user, oemuser__is_disabled=False)
    disabled_oems = OEMUser.objects.filter(Q(user = request.user) & Q(is_disabled = True))

    ## replied rfq
    replied_rfq = RFQReply.objects.filter(rfq_creator = request.user, is_viewed = False)

    p = Paginator(disabled_oems.order_by('-id'),25)
    page = request.GET.get('page')
    disabled = p.get_page(page)
    context = {'disabled_oems':disabled_oems,'oems':oems,'disabled':disabled,'replied_rfq':replied_rfq}
    return render(request,'solicitations/oems/disabled_oems.html',context)

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
def enable_oem(request, oem_id):
    if request.method == "POST":
        # Fetch the OEMUser object for the logged-in user
        enable_oem = get_object_or_404(OEMUser, id=oem_id, user=request.user)

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
    oem_obj = get_object_or_404(OEM, id=oem)
    
    # Check if the logged-in user is assigned to this OEM
    if not OEMUser.objects.filter(user=request.user, oem=oem_obj, is_disabled=False).exists():
        return HttpResponseForbidden("You do not have permission to edit this OEM.")
    
    # Get or create the user's customization for this OEM
    customization, created = UserOEMCustomization.objects.get_or_create(
        user=request.user,
        oem=oem_obj
    )
    
    if request.method == "POST":
        form = UserOEMCustomizationForm(request.POST, instance=customization)
        if form.is_valid():
            form.save()
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
            }
            form = UserOEMCustomizationForm(initial=initial_data, instance=customization)
    
    return render(request, 'solicitations/oems/edit_oem.html', {'form': form, 'oem': oem_obj})

def add_oem(request):
    """View to handle manual OEM addition through the modal form"""
    if request.method == 'POST':
        # Print received data for debugging
        print("="*50)
        print("Received POST data for manual add:", request.POST)
        
        try:
            # Extract OEM data from form
            name = request.POST.get('name')
            cage = request.POST.get('cage')
            email = request.POST.get('email')
            phone = request.POST.get('phone')
            fax = request.POST.get('fax', '')  # Optional field
            city = request.POST.get('city')
            street = request.POST.get('street')
            postal_code = request.POST.get('postal_code')
            
            # Print extracted values
            print("Extracted values:")
            print(f"Name: {name}, Cage: {cage}, Email: {email}")
            print(f"Phone: {phone}, Fax: {fax}, City: {city}")
            print(f"Street: {street}, Postal Code: {postal_code}")
            
            # Validate required fields
            required_fields = {'name': name, 'cage': cage, 'email': email, 
                              'phone': phone, 'city': city, 'street': street, 
                              'postal_code': postal_code}
            
            missing_fields = [field for field, value in required_fields.items() if not value]
            
            if missing_fields:
                error_msg = f"Missing required fields: {', '.join(missing_fields)}"
                print("ERROR:", error_msg)
                messages.error(request, error_msg)
                return redirect('solicitations:active-oems')
                
            # Check if an OEM with the same cage code already exists
            if OEM.objects.filter(cage=cage).exists():
                error_msg = f"An OEM with cage code '{cage}' already exists."
                print("WARNING:", error_msg)
                messages.error(request, error_msg)
                return redirect('solicitations:active-oems')
            
            # Create new OEM
            new_oem = OEM(
                name=name,
                cage=cage,
                email=email,
                phone=phone,
                fax=fax,
                city=city,
                street=street,
                postal_code=postal_code
            )
            
            print("Attempting to save OEM to database...")
            new_oem.save()
            print(f"SUCCESS: Created OEM '{name}' with ID {new_oem.id}")
            
            # Associate OEM with the current user
            user_oem = OEMUser(
                user=request.user,
                oem=new_oem,
                is_disabled=False
            )
            user_oem.save()
            print(f"SUCCESS: Associated OEM '{name}' with user '{request.user.username}'")
            
            messages.success(request, f"OEM '{name}' has been added successfully and associated with your account.")
            
        except Exception as e:
            # Print the full error with traceback
            print("ERROR creating OEM:", str(e))
            print(traceback.format_exc())
            messages.error(request, f"Error creating OEM: {str(e)}")
            
        print("="*50)
        return redirect('solicitations:active-oems')
    
    # If not POST, redirect to active-oems
    return redirect('solicitations:active-oems')

def import_oem(request):
    """View to handle OEM import from Excel file"""
    if request.method == 'POST':
        print("="*50)
        print("Received Excel import request")
        
        if 'excel_file' not in request.FILES:
            print("ERROR: No file uploaded")
            messages.error(request, "No file uploaded. Please select an Excel file.")
            return redirect('solicitations:active-oems')
            
        excel_file = request.FILES['excel_file']
        print(f"Received file: {excel_file.name}, size: {excel_file.size} bytes")
        
        # Check file extension
        if not excel_file.name.endswith(('.xlsx', '.xls')):
            print(f"ERROR: Invalid file format: {excel_file.name}")
            messages.error(request, "Unsupported file format. Please upload an Excel file (.xlsx, .xls).")
            return redirect('solicitations:active-oems')
        
        try:
            # Read Excel file
            print("Reading Excel file...")
            df = pd.read_excel(excel_file)
            print(f"Excel file read successfully. Found {len(df)} rows.")
            
            # Print the columns found
            print(f"Columns in file: {list(df.columns)}")
            
            # Check required columns
            required_columns = ['name', 'cage', 'email', 'phone', 'city', 'street', 'postal_code']
            missing_columns = [col for col in required_columns if col not in df.columns]
            
            if missing_columns:
                error_msg = f"Missing required columns: {', '.join(missing_columns)}"
                print("ERROR:", error_msg)
                messages.error(request, error_msg)
                return redirect('solicitations:active-oems')
            
            # Count successful and skipped imports
            success_count = 0
            skip_count = 0
            error_count = 0
            
            # Process each row
            for index, row in df.iterrows():
                try:
                    # Print the current row being processed (first 5 rows only)
                    if index < 5:
                        print(f"Processing row {index}: {row.to_dict()}")
                    
                    # Check for missing required values
                    missing_values = [col for col in required_columns if pd.isna(row[col]) or row[col] == '']
                    if missing_values:
                        print(f"WARNING - Row {index}: Missing values for {missing_values}. Skipping.")
                        error_count += 1
                        continue
                        
                    # Check if OEM with this cage already exists
                    cage = str(row['cage']).strip()
                    if OEM.objects.filter(cage=cage).exists():
                        print(f"INFO - Row {index}: OEM with cage {cage} already exists. Skipping.")
                        skip_count += 1
                        continue
                    
                    # Handle optional fax field
                    fax = str(row.get('fax', '')) if 'fax' in df.columns and not pd.isna(row.get('fax', '')) else ''
                    
                    # Create new OEM
                    new_oem = OEM(
                        name=str(row['name']).strip(),
                        cage=cage,
                        email=str(row['email']).strip(),
                        phone=str(row['phone']).strip(),
                        fax=fax,
                        city=str(row['city']).strip(),
                        street=str(row['street']).strip(),
                        postal_code=str(row['postal_code']).strip()
                    )
                    
                    print(f"Saving row {index} with cage {cage}...")
                    new_oem.save()
                    print(f"Row {index}: Successfully saved OEM with ID {new_oem.id}")
                    
                    # Associate OEM with the current user
                    user_oem = OEMUser(
                        user=request.user,
                        oem=new_oem,
                        is_disabled=False
                    )
                    user_oem.save()
                    print(f"Row {index}: Associated OEM with user '{request.user.username}'")
                    
                    success_count += 1
                    
                except Exception as e:
                    print(f"ERROR - Row {index}: {str(e)}")
                    error_count += 1
            
            # Show success message
            print(f"Import complete. Success: {success_count}, Skipped: {skip_count}, Errors: {error_count}")
            
            if success_count > 0:
                messages.success(request, f"Successfully imported {success_count} OEMs and associated them with your account. Skipped {skip_count} duplicate entries. Errors: {error_count}.")
            else:
                messages.warning(request, f"No new OEMs imported. Skipped {skip_count} duplicate entries. Errors: {error_count}.")
                
        except Exception as e:
            print("ERROR processing Excel file:", str(e))
            print(traceback.format_exc())
            messages.error(request, f"Error processing Excel file: {str(e)}")
        
        print("="*50)
        return redirect('solicitations:active-oems')
    
    # If not POST, redirect to active-oems
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

################ CHAT VIEWS  #######################################

def send_chat_notification_email(message):
    """
    Send an email notification about a new chat message to the recipient
    
    Args:
        message: RFQChatMessage instance
    """
    
    print("Starting email function")
    
    # Determine the recipient
    if message.sender == message.chat.rfq.created_by:
        # Sender is the vendor, recipient is the supplier (OEM)
        
        # First, check if there's a customization for this OEM and sender
        customization = UserOEMCustomization.objects.filter(
            user=message.sender,
            oem=message.chat.rfq.oem
        ).first()
        
        if customization and customization.custom_email:
            # Use the customized email if available
            recipient_email = customization.custom_email
            recipient_name = customization.custom_name or message.chat.rfq.oem.name
            print(f"Using customized OEM email: {recipient_name} ({recipient_email})")
        else:
            # Fall back to the OEM's default email
            recipient_email = message.chat.rfq.oem.email
            recipient_name = message.chat.rfq.oem.name
            print(f"Using default OEM email: {recipient_name} ({recipient_email})")
    else:
        # Sender is the supplier, recipient is the vendor
        recipient = message.chat.rfq.created_by
        recipient_email = recipient.email
        recipient_name = recipient.get_full_name() or recipient.username
        print(f"Recipient is Vendor: {recipient_name} ({recipient_email})")
    
    # Get chat URL
    chat_url = settings.BASE_URL + reverse('solicitations:rfq_chat_detail', kwargs={'rfq_id': message.chat.rfq.unique_id})
    print(f"Generated chat URL: {chat_url}")
    
    # Get message preview (truncate if too long)
    message_preview = message.content[:100] + ('...' if len(message.content) > 100 else '')
    
    # Get sender name
    sender_name = message.sender.get_full_name() or message.sender.username
    
    # Prepare email context
    context = {
        'recipient_name': recipient_name,
        'sender_name': sender_name,
        'rfq_id': message.chat.rfq.unique_id,
        'rfq_nomenclature': message.chat.rfq.solicitation.nomenclature,
        'message_preview': message_preview,
        'chat_url': chat_url,
        'company_name': 'Your Company Name',  
    }
    
    # Render email templates
    subject = f"New message regarding RFQ-{message.chat.rfq.unique_id}"
    
    try:
        html_message = render_to_string('solicitations/emails/vendor_notification.html', context)
        plain_message = render_to_string('solicitations/emails/vendor_notification.txt', context)
        
        print(f"Attempting to send email to: {recipient_email}")
        
        # Send the email
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_email],
            html_message=html_message,
            fail_silently=False,
        )
        print("Email sent successfully")
        return True
    except Exception as e:
        # Log the error but don't crash the application
        print(f"Error sending notification email: {e}")
        return False
    

def rfq_chat_detail(request, rfq_id):
    """
    View to display the chat interface for a specific RFQ
    """
    # Get the RFQ instance
    rfq = get_object_or_404(RFQ, unique_id=rfq_id)
    
    # Check if the user has permission to view this chat
    # User must be either the vendor (RFQ creator) or the supplier (OEM user)
    is_vendor = request.user == rfq.created_by
    is_supplier = request.user in rfq.oem.users.all()
    
    if not (is_vendor or is_supplier):
        return HttpResponseForbidden("You don't have permission to access this chat.")
    
    # Get the associated RFQ reply for the back button
    rfq_reply = None
    if is_supplier:
        rfq_reply = RFQReply.objects.filter(rfq=rfq, rfq_creator=request.user).first()
    else:  # is_vendor
        rfq_reply = RFQReply.objects.filter(rfq=rfq).first()
    
    # Get or create the chat for this RFQ
    chat, created = RFQChat.objects.get_or_create(rfq=rfq)
    
    # Mark all unread messages as read
    unread_messages = chat.messages.filter(is_read=False).exclude(sender=request.user)
    for message in unread_messages:
        message.mark_as_read()
    
    # If the user submitted a new message
    if request.method == 'POST':
        message_content = request.POST.get('message')
        attachment = request.FILES.get('attachment')
        
        if message_content or attachment:
            # Create the new message
            new_message = RFQChatMessage.objects.create(
                chat=chat,
                sender=request.user,
                content=message_content or '',
                attachment=attachment,
                attachment_name=attachment.name if attachment else None
            )
            
            # Send email notification
            send_chat_notification_email(new_message)
            
            # Redirect to prevent form resubmission
            return redirect('solicitations:rfq_chat_detail', rfq_id=rfq_id)
        else:
            messages.error(request, "Message cannot be empty.")
    
    # Get all messages for this chat
    chat_messages = chat.messages.all()
    
    # Prepare context for the template
    context = {
        'rfq': rfq,
        'chat': chat,
        'chat_messages': chat_messages,
        'is_vendor': is_vendor,
        'is_supplier': is_supplier,
        'rfq_reply': rfq_reply,
    }
    
    return render(request, 'solicitations/chat/chat_detail.html', context)

def send_chat_notification_email(message):
    """
    Send an email notification about a new chat message to the recipient
    """
    
    try:
        print("Starting email notification process")
        
        # Determine the recipient
        if message.sender == message.chat.rfq.created_by:
            # Sender is the vendor, recipient is the supplier (OEM)
            print("Sender is the vendor, recipient is the supplier (OEM)")
            
            # First, check if there's a customization for this OEM and sender
            customization = UserOEMCustomization.objects.filter(
                user=message.sender,
                oem=message.chat.rfq.oem
            ).first()
            
            if customization and customization.custom_email:
                # Use the customized email if available
                recipient_email = customization.custom_email
                recipient_name = customization.custom_name or message.chat.rfq.oem.name
                print(f"Using customized email: {recipient_email}, name: {recipient_name}")
            else:
                # Fall back to the OEM's default email
                recipient_email = message.chat.rfq.oem.email
                recipient_name = message.chat.rfq.oem.name
                print(f"Using OEM default email: {recipient_email}, name: {recipient_name}")
                
            # OEM recipients need the public chat URL with token
            access_token = generate_oem_access_token(message.chat.rfq)
            chat_url = settings.BASE_URL + reverse('solicitations:public_rfq_chat', 
                                                 kwargs={
                                                     'rfq_id': message.chat.rfq.unique_id, 
                                                     'access_token': access_token
                                                 })
            print(f"Generated OEM chat URL: {chat_url}")
        else:
            # Sender is the supplier, recipient is the vendor
            print("Sender is the supplier, recipient is the vendor")
            recipient = message.chat.rfq.created_by
            recipient_email = recipient.email
            recipient_name = recipient.get_full_name() or recipient.username
            print(f"Using vendor email: {recipient_email}, name: {recipient_name}")
            
            # Vendor recipients use the authenticated chat URL
            chat_url = settings.BASE_URL + reverse('solicitations:rfq_chat_detail', 
                                                 kwargs={'rfq_id': message.chat.rfq.unique_id})
            print(f"Generated vendor chat URL: {chat_url}")
        
        # Validate recipient email
        if not recipient_email or '@' not in recipient_email:
            print(f"ERROR: Invalid recipient email: {recipient_email}")
            return False
            
        # Log the recipient email for debugging
        print(f"Sending notification email to: {recipient_email}")
        
        # Get message preview (truncate if too long)
        message_preview = message.content[:100] + ('...' if len(message.content) > 100 else '')
        print(f"Message preview: {message_preview}")
        
        # Get sender name
        sender_name = message.sender.get_full_name() or message.sender.username
        print(f"Sender name: {sender_name}")
        
        # Get RFQ details - handle multiple items
        rfq = message.chat.rfq
        
        # Check if this RFQ has multiple items
        rfq_items = RFQItem.objects.filter(rfq=rfq)
        
        if rfq_items.exists():
            print(f"Found {rfq_items.count()} items for this RFQ")
            # This RFQ has multiple items
            items = []
            for item in rfq_items:
                solicitation = item.solicitation
                items.append({
                    'part_number': solicitation.part_number if hasattr(solicitation, 'part_number') else "N/A",
                    'quantity': solicitation.quantity if hasattr(solicitation, 'quantity') else "N/A",
                    'nomenclature': solicitation.nomenclature if hasattr(solicitation, 'nomenclature') else "N/A",
                    'nsn': solicitation.NSN if hasattr(solicitation, 'NSN') else "N/A",
                    'unit': solicitation.unit if hasattr(solicitation, 'unit') else "N/A"
                })
                print(f"Item added: {items[-1]}")
        else:
            # Single solicitation attached directly to RFQ
            print("No RFQ items found, using the main solicitation")
            solicitation = rfq.solicitation
            items = [{
                'part_number': solicitation.part_number if hasattr(solicitation, 'part_number') else "N/A",
                'quantity': solicitation.quantity if hasattr(solicitation, 'quantity') else "N/A",
                'nomenclature': solicitation.nomenclature if hasattr(solicitation, 'nomenclature') else "N/A",
                'nsn': solicitation.NSN if hasattr(solicitation, 'NSN') else "N/A",
                'unit': solicitation.unit if hasattr(solicitation, 'unit') else "N/A"
            }]
            print(f"Single item: {items[0]}")
        
        # Check email settings
        print(f"Email settings check - FROM_EMAIL: {settings.DEFAULT_FROM_EMAIL}")
        print(f"Email settings check - EMAIL_HOST: {settings.EMAIL_HOST}")
        print(f"Email settings check - EMAIL_PORT: {settings.EMAIL_PORT}")
        
        # Prepare email context
        context = {
            'recipient_name': recipient_name,
            'sender_name': sender_name,
            'rfq_id': rfq.unique_id,
            'rfq_nomenclature': rfq.solicitation.nomenclature,  # Primary solicitation nomenclature
            'message_preview': message_preview,
            'chat_url': chat_url,
            'company_name': 'Your Company Name',
            'items': items,  # Pass the list of items
            # For backwards compatibility, include the first item's details directly
            'part_number': items[0]['part_number'] if items else "N/A",
            'quantity': items[0]['quantity'] if items else "N/A",
        }
        print("Email context prepared")
        
        # Render email templates
        template_html = 'solicitations/emails/vendor_notification.html'
        template_text = 'solicitations/emails/vendor_notification.txt'
        
        subject = f"New message regarding RFQ-{rfq.unique_id}"
        print(f"Email subject: {subject}")
        
        try:
            print(f"Attempting to render email templates: {template_html} and {template_text}")
            html_message = render_to_string(template_html, context)
            plain_message = render_to_string(template_text, context)
            print("Email templates rendered successfully")
            
            # Send the email
            print(f"Attempting to send email to {recipient_email}...")
            result = send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient_email],
                html_message=html_message,
                fail_silently=False,
            )
            
            # Log the result
            print(f"Email send attempt result: {result}")
            return True
            
        except Exception as e:
            print(f"ERROR: Email rendering/sending failed: {str(e)}")
            import traceback
            print(traceback.format_exc())  # Print full traceback
            return False
            
    except Exception as e:
        print(f"ERROR: General error in send_chat_notification_email: {str(e)}")
        import traceback
        print(traceback.format_exc())  # Print full traceback
        return False

def generate_oem_access_token(rfq):
    """
    Generate a secure access token for the OEM to access the chat
    """
    from django.core.signing import Signer
    import base64
    
    # Create a unique token value based on the RFQ and OEM email
    signer = Signer()
    token_value = f"rfq_chat_{rfq.unique_id}_{rfq.oem.email}"
    
    # Sign the token
    signed_token = signer.sign(token_value)
    
    # Base64 encode the token to make it URL-safe
    encoded_token = base64.urlsafe_b64encode(signed_token.encode()).decode()
    
    return encoded_token

def send_chat_message_ajax(request, rfq_id):
    """
    AJAX view to send a new chat message without reloading the page
    """
    # Get the RFQ instance
    rfq = get_object_or_404(RFQ, unique_id=rfq_id)
    
    # Check permissions
    is_vendor = request.user == rfq.created_by
    is_supplier = request.user in rfq.oem.users.all()
    
    if not (is_vendor or is_supplier):
        return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)
    
    # Get message content
    message_content = request.POST.get('message')
    attachment = request.FILES.get('attachment')
    
    if not message_content and not attachment:
        return JsonResponse({'status': 'error', 'message': 'Message cannot be empty'}, status=400)
    
    # Get or create the chat
    chat, created = RFQChat.objects.get_or_create(rfq=rfq)
    
    # Create the message
    message = RFQChatMessage.objects.create(
        chat=chat,
        sender=request.user,
        content=message_content or '',
        attachment=attachment,
        attachment_name=attachment.name if attachment else None
    )
    
    # Send email notification
    send_chat_notification_email(message)
    
    # Prepare the response data
    message_data = {
        'id': message.id,
        'content': message.content,
        'timestamp': message.timestamp.strftime('%Y-%m-%d %H:%M'),
        'sender_name': request.user.get_full_name() or request.user.username,
        'is_own_message': True,
        'has_attachment': bool(message.attachment),
        'attachment_url': message.attachment.url if message.attachment else None,
        'attachment_name': message.attachment_name,
    }
    
    return JsonResponse({'status': 'success', 'message': message_data})


def get_new_messages_ajax(request, rfq_id):
    """
    AJAX view to get new messages without reloading the page
    """
    # Get the RFQ instance
    rfq = get_object_or_404(RFQ, unique_id=rfq_id)
    
    # Check permissions
    is_vendor = request.user == rfq.created_by
    is_supplier = request.user in rfq.oem.users.all()
    
    if not (is_vendor or is_supplier):
        return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)
    
    # Get the last message ID the client has
    last_message_id = request.GET.get('last_message_id', 0)
    
    # Get or create the chat
    chat, created = RFQChat.objects.get_or_create(rfq=rfq)
    
    # Get new messages
    new_messages = chat.messages.filter(id__gt=last_message_id)
    
    # Mark messages as read if they're not from the current user
    for message in new_messages:
        if message.sender != request.user and not message.is_read:
            message.mark_as_read()
    
    # Prepare message data for JSON response
    messages_data = []
    for message in new_messages:
        messages_data.append({
            'id': message.id,
            'content': message.content,
            'timestamp': message.timestamp.strftime('%Y-%m-%d %H:%M'),
            'sender_name': message.sender.get_full_name() or message.sender.username,
            'is_own_message': message.sender == request.user,
            'has_attachment': bool(message.attachment),
            'attachment_url': message.attachment.url if message.attachment else None,
            'attachment_name': message.attachment_name,
        })
    
    return JsonResponse({'status': 'success', 'messages': messages_data})


def rfq_chats_list(request):
    """
    View to display a list of all active chats for the current user
    """
    # Get all RFQs where the user is either vendor or supplier
    vendor_rfqs = RFQ.objects.filter(created_by=request.user)
    supplier_rfqs = RFQ.objects.filter(oem__users=request.user)
    
    # Find RFQs with active chats
    vendor_chats = RFQChat.objects.filter(rfq__in=vendor_rfqs, is_active=True)
    supplier_chats = RFQChat.objects.filter(rfq__in=supplier_rfqs, is_active=True)
    
    # Count unread messages for each chat
    for chat in list(vendor_chats) + list(supplier_chats):
        chat.unread_count = chat.get_unread_count_for_user(request.user)
    
    context = {
        'vendor_chats': vendor_chats,
        'supplier_chats': supplier_chats,
    }
    
    return render(request, 'solicitations/chat/chats_list.html', context)

def public_rfq_chat(request, rfq_id, access_token):
    """
    Public view for OEMs without accounts to view and reply to chat messages
    """
    
    # Get the RFQ instance
    rfq = get_object_or_404(RFQ, unique_id=rfq_id)
    
    try:
        # Decode the token from base64
        decoded_token = base64.urlsafe_b64decode(access_token.encode()).decode()
        
        # Verify the token
        signer = Signer()
        verified_value = signer.unsign(decoded_token)
        
        # Check if the verified value matches what we expect
        expected_value = f"rfq_chat_{rfq_id}_{rfq.oem.email}"
        if verified_value != expected_value:
            return HttpResponseForbidden("Invalid access token.")
    except Exception as e:
        return HttpResponseForbidden("Invalid or expired access token.")
    
    # Get or create the chat for this RFQ
    chat, created = RFQChat.objects.get_or_create(rfq=rfq)
    
    # Process form submission
    if request.method == 'POST':
        message_content = request.POST.get('message')
        attachment = request.FILES.get('attachment')
        
        if message_content or attachment:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            
            # Force create a different user for OEM messages
            oem_email = rfq.oem.email
            oem_username = f"oem_{rfq.oem.cage.lower()}_public"
            
            try:
                oem_user = User.objects.get(username=oem_username)
                print(f"Found existing public OEM user: {oem_user.id} - {oem_user.username}")
            except User.DoesNotExist:
                # Create a new user
                oem_user = User.objects.create_user(
                    username=oem_username,
                    email=oem_email,
                    password=User.objects.make_random_password(),
                    first_name=f"OEM {rfq.oem.name[:20]}"
                )
                print(f"Created new public OEM user: {oem_user.id} - {oem_user.username}")
            
            print(f"Using specific public OEM user: {oem_user.id} - {oem_user.username}")
            
            # Create message with this specific OEM user
            message = RFQChatMessage.objects.create(
                chat=chat,
                sender=oem_user,
                content=message_content or '',
                attachment=attachment,
                attachment_name=attachment.name if attachment else None
            )
            
            # Verify the message was created with the correct sender
            print(f"Message created with sender ID: {message.sender.id}, username: {message.sender.username}")
            
            # Show success message
            messages.success(request, "Your message has been sent successfully.")
            
            # Redirect to prevent form resubmission
            return redirect('solicitations:public_rfq_chat', rfq_id=rfq_id, access_token=access_token)
    
    # Get all messages for this chat
    chat_messages = chat.messages.all()
    
    # Add a flag to each message to indicate if it's from the vendor
    for message in chat_messages:
        message.is_from_vendor = (message.sender == rfq.created_by)
    
    # Prepare context for the template
    context = {
        'rfq': rfq,
        'chat': chat,
        'chat_messages': chat_messages,
        'access_token': access_token,
        'oem_name': rfq.oem.name,
    }
    
    return render(request, 'solicitations/chat/public_rfq_chat.html', context)


# view to show client detail
def user_profile(request, client):
    client_user = request.user
    logo_form = LogoUpdateForm(instance=client_user)
    user_form = UserUpdateForm(instance=client_user)
    
    if request.method == 'POST':
        if 'logo_update' in request.POST:
            # Add debugging print statements
            print("Processing logo update")
            print(f"FILES: {request.FILES}")
            
            logo_form = LogoUpdateForm(request.POST, request.FILES, instance=client_user)
            if logo_form.is_valid():
                print("Logo form is valid")
                logo_form.save()
                messages.success(request, 'Your logo has been updated successfully!')
                return redirect('solicitations:user-profile', client=client)
            else:
                # Print form errors to help debug
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
    
    context = {
        'client': client_user,
        'logo_form': logo_form,
        'user_form': user_form
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

        # 3. Send email with new invitation
        invite_url = request.build_absolute_uri(
            reverse('accounts:register_with_invitation', args=[str(invitation.token)])
        )
        
        subject = 'Your Invitation'
        message = f'''
        Hello,
        
        Here's your registration link:
        {invite_url}
        
        Expires: {invitation.expires_at.strftime('%Y-%m-%d')}
        '''
        
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email])
        
        messages.success(request, f"Invitation sent to {email}")
        return redirect('solicitations:invite_user')

    return render(request, 'solicitations/clients/invite_user.html')