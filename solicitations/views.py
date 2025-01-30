import json
import os
from django.core.mail import send_mail
from django.conf import settings
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponseForbidden, HttpResponseNotFound, JsonResponse
from accounts.models import CustomUser
from . models import RFQ, MailTemplate, OEMUser, RFQReply, Solicitation,OEM
from django.contrib import messages
import subprocess
from . forms import LogoUpdateForm, UserRegistrationForm,RFQReplyForm
from django.core.paginator import Paginator
from django.db.models import Q
from django.template.loader import render_to_string
from datetime import datetime

# Create your views here.

def base(request):
    ## replied rfq
    replied_rfq = RFQReply.objects.filter(rfq_creator = request.user, is_viewed = False)

    ## pass data to the template
    context = {
        'replied_rfq':replied_rfq
        }
    return render(request,'solicitations/base.html',context)

def home(request):
    user=request.user
    ## fetch all normal users
    clients = CustomUser.objects.exclude(is_superuser=True).filter(user_type = 'client')
    ## count all normal users
    total_clients = clients.count()

    ## fetch all solicitaions
    solicitations = Solicitation.objects.all().exclude(cage = '-')

    ## count total number of solicitations
    total_solicitations = solicitations.count()

    # fetch user rfqs
    sent_rfqs = RFQ.objects.filter(created_by = request.user)
    # count all rfqs
    total_sent_rfqs = sent_rfqs.count()

    ## replied rfq
    replied_rfq = RFQReply.objects.filter(rfq_creator = request.user, is_viewed = False)
    ## pass data to the template
    context = {
        'total_clients':total_clients,'total_solicitations':total_solicitations,
        'sent_rfqs':sent_rfqs,'total_sent_rfqs':total_sent_rfqs,'replied_rfq':replied_rfq,
        }
    return render(request,'solicitations/home.html',context)

## view to show all solicitations
def solicitations(request):
    ## fetch all solicitaions
    solicitations = Solicitation.objects.all().exclude(cage='-')
    ## count total number of solicitations
    total_solicitations = solicitations.count()

    ## replied rfq
    replied_rfq = RFQReply.objects.filter(rfq_creator = request.user, is_viewed = False)
    ## pass data to the template
    context = {'total_solicitations':total_solicitations,'solicitations':solicitations,'replied_rfq':replied_rfq}
    return render(request,'solicitations/solicitations.html',context)

## view to show solicitation detail
def solicitation_detail(request,solicitation):
    solicitation_detail = Solicitation.objects.get(pk=solicitation)
    oem = OEM.objects.filter(cage=solicitation_detail.cage).first()
    ## replied rfq
    replied_rfq = RFQReply.objects.filter(rfq_creator = request.user, is_viewed = False)
    context = {"solicitation_detail":solicitation_detail,"oem":oem,'replied_rfq':replied_rfq}
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
                Q(cage__icontains=mysearch) | Q(NSN__icontains=mysearch)
            )
            print(f'YOOOOOOOOOOOOOOOOO {data}')  # Debugging print statement
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

    # Get input dates from POST data
    issued = request.POST.get('issued_date')
    return_by = request.POST.get('return_by_date')

    if issued:
        # Convert yyyy-mm-dd to mm-dd-yyyy
        issued_date_obj = datetime.strptime(issued, '%Y-%m-%d')
        issued_date_str = issued_date_obj.strftime('%m-%d-%Y')
        solicitations = solicitations.filter(issued_date__exact=issued_date_str)

    if return_by:
        # Convert yyyy-mm-dd to mm-dd-yyyy
        return_by_date_obj = datetime.strptime(return_by, '%Y-%m-%d')
        return_by_date_str = return_by_date_obj.strftime('%m-%d-%Y')
        print(f'Return by date: {return_by_date_str}')
        solicitations = solicitations.filter(return_by_date__exact=return_by_date_str)

    # Render the filtered solicitations
    return render(request, 'solicitations/filtered_solicitations.html', {'solicitations': solicitations})
#######################  CLIENT RELATED VIEWS  #########################

## view to show all clients
def clients(request):
    clients = CustomUser.objects.exclude(is_superuser=True).filter(user_type = 'client')
    total_clients = clients.count()
    ## replied rfq
    replied_rfq = RFQReply.objects.filter(rfq_creator = request.user, is_viewed = False)
    context = {"clients":clients,'total_clients':total_clients,'replied_rfq':replied_rfq}
    return render(request,'solicitations/clients/clients.html',context)

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
    
    ## replied rfq
    replied_rfq = RFQReply.objects.filter(rfq_creator = request.user, is_viewed = False)
    context = {'rfq': rfq,'replied_rfq':replied_rfq}
    return render(request, 'solicitations/procurements/rfq_detail.html', context)

##view to delete RFQ
def delete_rfq(request,rfq):
    delete_rfq = RFQ.objects.get(pk=rfq)
    delete_rfq.delete()
    return redirect('solicitations:sent-rfq')

## this is for displaying form for reply
def rfq_reply_view(request):
    user = request.user

    rfq_unique_id = request.GET.get('rfq_unique_id')  # Get the unique_id from query params
    rfq = get_object_or_404(RFQ, unique_id=rfq_unique_id)  # Fetch RFQ by unique_id
    solicitation = rfq.solicitation

    # Initialize the form variable
    form = RFQReplyForm()

    # Check if there's already a reply for this RFQ by this user
    if RFQReply.objects.filter(rfq=rfq, rfq_creator=user).exists():
        # Add a message to show to the user
        messages.error(request, "You have already submitted a reply for this RFQ.")
        return render(request, 'solicitations/procurements/rfq_reply.html', {
            'form': form, 'rfq': rfq, 'solicitation': solicitation, 'already_replied': True
        })

    if request.method == 'POST':
        form = RFQReplyForm(request.POST, request.FILES)
        if form.is_valid():
            rfq_reply = form.save(commit=False)
            rfq_reply.rfq = rfq  # Get the unsaved RFQ instance
            rfq_reply.rfq_creator = user  # Associate the reply with the RFQ
            rfq_reply.save()
            return JsonResponse({"success": True})

    return render(request, 'solicitations/procurements/rfq_reply.html', {
        'form': form, 'rfq': rfq, 'solicitation': solicitation, 'already_replied': False
    })

## view to show all replied views
def replied_rfq(request):
    # Fetch all RFQ replies, ordered by the latest first
    replied_rfq_queryset = RFQReply.objects.filter(rfq__created_by=request.user).order_by('-id')

    # Count all RFQs (total number of replies)
    total_replied_rfq = replied_rfq_queryset.filter(rfq__created_by=request.user).count()

    # Set up the paginator, 25 replies per page
    paginator = Paginator(replied_rfq_queryset, 25)
    page = request.GET.get('page')

    # Get the current page of replies
    rfq = paginator.get_page(page)

    # Fetch all RFQs
    sent_rfqs = RFQ.objects.filter(created_by=request.user)

    # Count all RFQs
    total_sent_rfqs = sent_rfqs.filter(created_by = request.user).count()

    ## replied rfq
    replied_rfq = RFQReply.objects.filter(rfq_creator = request.user, is_viewed = False)

    # Pass the paginated replies and total count to the template
    context = {
        'total_replied_rfq': total_replied_rfq,
        'rfq': rfq,
        'total_sent_rfqs': total_sent_rfqs,'replied_rfq':replied_rfq
    }
    return render(request, 'solicitations/procurements/replied_rfq.html', context)


## View to show Replied RFQ detail
def replied_rfq_detail(request, rfq):
    # Retrieve the RFQReply object or return a 404 error if it doesn't exist
    rfq_instance = get_object_or_404(RFQReply, pk=rfq)

    ## replied rfq
    replied_rfq = RFQReply.objects.filter(rfq_creator = request.user, is_viewed = False)
    
    # Toggle the is_viewed field to True
    if not rfq_instance.is_viewed:  # Update only if it's not already True
        rfq_instance.is_viewed = True
        rfq_instance.save()

    # Pass the RFQReply object to the template
    context = {'rfq': rfq_instance,'replied_rfq':replied_rfq}
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
        # Parse JSON data from the request body
        data = json.loads(request.body)
        selected_ids = data.get("selected_ids", [])  # Retrieve selected IDs from the request

        if not selected_ids:
            return JsonResponse({"error": "No solicitations selected"}, status=400)

        # Query the database for the selected IDs
        solicitations = Solicitation.objects.filter(id__in=selected_ids)

        if not solicitations.exists():
            return JsonResponse({"error": "No matching solicitations found"}, status=404)

        # Serialize the solicitation data
        solicitation_data = [
            {
                "id": sol.id,
                "cage": sol.cage,
                "nomenclature": sol.nomenclature,
                "quantity": sol.quantity,
                "return_by_date": sol.return_by_date,
                "NSN": sol.NSN,
            }
            for sol in solicitations
        ]

        # Get the logged-in user
        logged_in_user = request.user  

        # Retrieve the MailTemplate for the logged-in user
        mail_template = MailTemplate.objects.filter(userMail=logged_in_user).first()
        if not mail_template:
            return JsonResponse({"error": "No mail template found for the user"}, status=404)

        # Serialize the mail template data
        mail_data = {
            "salutation": mail_template.salutation,
            "heading": mail_template.heading,
            "body": mail_template.body,
        }

        # Serialize the user data
        user_data = {
            "username": logged_in_user.username,
            "email": logged_in_user.email,
            "phone": getattr(logged_in_user, "phone", None),
            "address": getattr(logged_in_user, "address", None),
            "companyName": getattr(logged_in_user, "companyName", None),
            "logo": logged_in_user.logo.url if hasattr(logged_in_user, "logo") and logged_in_user.logo else None,
        }

        # Combine all data
        combined_data = {
            "user_data": user_data,
            "mail_data": mail_data,
            "solicitations": solicitation_data,
        }

        # Debugging: Print combined data
        print(f"Combined data: {json.dumps(combined_data, indent=2)}")

        # Run the external script with the serialized data
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
            print(error_message)  # Log the error for debugging
            return JsonResponse({"error": error_message}, status=500)

        print(f"Subprocess output: {stdout}")  # Log subprocess output

        return JsonResponse({"message": stdout, "data": solicitation_data}, status=200)

    except Exception as e:
        error_message = f"Unexpected error: {str(e)}"
        print(error_message)  # Log unexpected errors
        return JsonResponse({"error": error_message}, status=500)

def get_chart_data(request):
    # Dynamic calculation for solicitation
    solicitations = Solicitation.objects.exclude(cage = '-').count() 

    # Dynamic calculation for "Replied" - count of replies for all RFQs
    replied = RFQReply.objects.filter(rfq_creator = request.user).count() 
    print(f'rREPLIED RFQS {replied}')

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
    print(oems)

    # Filter OEMs related to the user and are disabled for that user
    disabled_oems = OEM.objects.filter(oemuser__user=request.user, oemuser__is_disabled=True)
    print(disabled_oems)

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
    oem = get_object_or_404(OEM, pk=oem)

    # Get all OEMUser associations for this OEM
    oem_users = OEMUser.objects.filter(oem=oem)

    ## replied rfq
    replied_rfq = RFQReply.objects.filter(rfq_creator = request.user, is_viewed = False)

    # Pass the data to the template
    context = {'oem': oem, 'oem_users': oem_users,'replied_rfq':replied_rfq}
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




