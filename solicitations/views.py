import json
import os
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponseForbidden, HttpResponseNotFound, JsonResponse
from accounts.models import CustomUser
from . models import RFQ, OEMUser, RFQReply, Solicitation,OEM
from django.contrib.auth.hashers import check_password
from django.contrib import messages
import subprocess
from . forms import LogoUpdateForm, UserRegistrationForm,RFQReplyForm
from django.core.paginator import Paginator
from django.db.models import Q

# Create your views here.

def home(request):
    user=request.user
    ## fetch all normal users
    clients = CustomUser.objects.exclude(is_superuser=True).filter(user_type = 'client')
    ## count all normal users
    total_clients = clients.count()

    ## fetch all solicitaions
    
    solicitations = Solicitation.objects.all()

    ## count total number of solicitations
    total_solicitations = solicitations.count()

    # fetch all rfqs
    if user.is_superuser:
        sent_rfqs = RFQ.objects.all()
    else:
        sent_rfqs = RFQ.objects.filter(created_by = request.user)
    # count all rfqs
    total_sent_rfqs = sent_rfqs.count()

    ## pass data to the template
    context = {
        'total_clients':total_clients,'total_solicitations':total_solicitations,
        'sent_rfqs':sent_rfqs,'total_sent_rfqs':total_sent_rfqs
        }
    return render(request,'solicitations/home.html',context)

## view to show all solicitations
def solicitations(request):
    ## fetch all solicitaions
    solicitations = Solicitation.objects.all()
    ## count total number of solicitations
    total_solicitations = solicitations.count()
    ## pass data to the template
    context = {'total_solicitations':total_solicitations,'solicitations':solicitations}
    return render(request,'solicitations/solicitations.html',context)

## view to show all clients
def clients(request):
    clients = CustomUser.objects.exclude(is_superuser=True).filter(user_type = 'client')
    total_clients = clients.count()
    context = {"clients":clients,'total_clients':total_clients}
    return render(request,'solicitations/clients/clients.html',context)

## view add clients
def add_client(request):
    if request.method == 'POST':
        form = UserRegistrationForm(request.POST, request.FILES)

        if form.is_valid():
            form.save()
            return redirect('solicitations:clients')

    else:
        # If GET request, initialize the form
        form = UserRegistrationForm()

    return render(request,'solicitations/clients/add.html',{'form': form})

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
        
        # Handle password change form
        elif 'password_change' in request.POST:
            current_password = request.POST.get('password')
            new_password = request.POST.get('newpassword')
            renew_password = request.POST.get('renewpassword')

            # Validate current password
            if not check_password(current_password, client.password):
                messages.error(request, "Current password is incorrect.")
            # Validate new password confirmation
            elif new_password != renew_password:
                messages.error(request, "New passwords do not match.")
            else:
                # Update password in the database
                client.set_password(new_password)
                client.save()
                messages.success(request, "Password updated successfully!")
                return redirect('solicitations:client-details', client=client.pk)

    form = LogoUpdateForm(instance=client)
    context = {
        'client': client,
        'form': form,
    }
    return render(request, 'solicitations/clients/details.html', context)

## view to show all sent rfqs
def sent_rfq(request):
    # fetch all rfqs if user is admin
    if request.user.user_type == 'admin':
        sent_rfqs = RFQ.objects.all()
    else:
        sent_rfqs = RFQ.objects.filter(created_by=request.user)
    # count all rfqs
    if request.user.user_type == 'admin':
        total_sent_rfqs = sent_rfqs.count()
    else:
        total_sent_rfqs = sent_rfqs.filter(created_by=request.user).count()
    if request.user.user_type == 'admin':
        p = Paginator(RFQ.objects.order_by('-id'),10)
    else:
        p = Paginator(RFQ.objects.filter(created_by=request.user).order_by('-id'),10)
    page = request.GET.get('page')
    rfq = p.get_page(page)

    # Fetch all RFQ replies, ordered by the latest first
    replied_rfq_queryset = RFQReply.objects.all().order_by('-id')
    if request.user.user_type == 'admin':
        replied_rfq_queryse = RFQReply.objects.all().order_by('-id')
    else:
        replied_rfq_queryse = RFQReply.objects.filter(rfq__created_by=request.user).count()

    # Count all RFQs (total number of replies)
    if request.user.user_type == 'admin':
        total_replied_rfq = replied_rfq_queryset.count()
    else:
        total_replied_rfq = replied_rfq_queryset.filter(rfq__created_by=request.user).count()
    # pass data to template
    context = {'sent_rfqs':sent_rfqs,'total_sent_rfqs':total_sent_rfqs,'rfq':rfq,'total_replied_rfq':total_replied_rfq,'replied_rfq_queryse':replied_rfq_queryse}
    return render(request,'solicitations/procurements/sent_rfq.html',context)


#view to search for sent RFQS
def search_sent_rfq(request):
    if request.method == "POST":
        searched = request.POST['search-sent']
        
        if request.user.user_type == 'admin':
            rfqId = RFQ.objects.filter(unique_id__contains = searched)
        else:
            rfqId = RFQ.objects.filter(Q(unique_id__contains = searched) & Q(created_by = request.user))

        # fetch all rfqs if user is admin
        if request.user.user_type == 'admin':
            sent_rfqs = RFQ.objects.all()
            print("Fetching all RFQs")
        else:
            sent_rfqs = RFQ.objects.filter(created_by=request.user)
            print(f"Fetching RFQs for user: {request.user}")
            print(sent_rfqs)
        # count all rfqs
        if request.user.user_type == 'admin':
            total_sent_rfqs = sent_rfqs.count()
            print(total_sent_rfqs)
        else:
            total_sent_rfqs = sent_rfqs.filter(created_by=request.user).count()
            print(total_sent_rfqs)

        # Fetch all RFQ replies, ordered by the latest first
        if request.user.user_type == 'admin':
            replied_rfq_queryset = RFQReply.objects.all().order_by('-id')
        else:
            replied_rfq_queryset = RFQReply.objects.filter(rfq__created_by=request.user).order_by('-id')

        # Count all RFQs (total number of replies)
        if request.user.user_type == 'admin':
            total_replied_rfq = replied_rfq_queryset.count()
            print(f'total replied for user admin {total_replied_rfq}')
        else:
            total_replied_rfq = replied_rfq_queryset.filter(rfq__created_by=request.user).count()
            print(f'total replied for normal user {total_replied_rfq}')

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
    context = {'rfq': rfq}
    return render(request, 'solicitations/procurements/rfq_detail.html', context)

##view to delete RFQ
def delete_rfq(request,rfq):
    delete_rfq = RFQ.objects.get(pk=rfq)
    delete_rfq.delete()
    return redirect('solicitations:sent-rfq')

## this is for displaying form for reply
def rfq_reply_view(request):
    user = request.user
    print(user.username)

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


def replied_rfq(request):
    # Fetch all RFQ replies, ordered by the latest first
    if request.user.user_type == 'admin':
        replied_rfq_queryset = RFQReply.objects.all().order_by('-id')
    else:
        replied_rfq_queryset = RFQReply.objects.filter(rfq__created_by=request.user).order_by('-id')

    # Count all RFQs (total number of replies)
    if request.user.user_type == 'admin':
        total_replied_rfq = replied_rfq_queryset.count()
        print(f'total replied for user admin {total_replied_rfq}')
    else:
        total_replied_rfq = replied_rfq_queryset.filter(rfq__created_by=request.user).count()
        print(f'total replied for normal user {total_replied_rfq}')

    # Set up the paginator, 10 replies per page
    paginator = Paginator(replied_rfq_queryset, 10)
    page = request.GET.get('page')

    # Get the current page of replies
    rfq = paginator.get_page(page)

    # Fetch all RFQs
    if request.user.user_type == 'admin':
        sent_rfqs = RFQ.objects.all()
    else:
        sent_rfqs = RFQ.objects.filter(created_by=request.user)

    # Count all RFQs
    if request.user.user_type == 'admin':
        total_sent_rfqs = sent_rfqs.count()
    else:
        total_sent_rfqs = sent_rfqs.filter(created_by = request.user).count()

    # Pass the paginated replies and total count to the template
    context = {
        'total_replied_rfq': total_replied_rfq,
        'rfq': rfq,
        'total_sent_rfqs': total_sent_rfqs
    }
    return render(request, 'solicitations/procurements/replied_rfq.html', context)


## View to show Replied RFQ detail
def replied_rfq_detail(request, rfq):
    rfq = RFQReply.objects.get(pk=rfq)
    context = {'rfq': rfq}
    return render(request, 'solicitations/procurements/replied_rfq_detail.html', context)

#view to search for Replied RFQS
def search_replied_rfq(request):
    if request.method == "POST":
        searched = request.POST['search-replied']
        
        if request.user.user_type == 'admin':
            # Access unique_id through the related RFQ
            replied_rfq_queryset = RFQReply.objects.filter(rfq__unique_id__icontains=searched).order_by('-id')
        else:
            # Combine conditions for non-admin users
            replied_rfq_queryset = RFQReply.objects.filter(
                Q(rfq__unique_id__icontains=searched) & 
                Q(rfq_creator=request.user)
            ).order_by('-id')

        # Count all Replied RFQs
        if request.user.user_type == 'admin':
            total_replied_rfq = RFQReply.objects.all().count()
        else:
            total_replied_rfq = RFQReply.objects.filter(rfq_creator=request.user).count()

        # Fetch Sent RFQs
        if request.user.user_type == 'admin':
            sent_rfqs = RFQ.objects.all()
        else:
            sent_rfqs = RFQ.objects.filter(created_by=request.user)

        # Count all Sent RFQs
        total_sent_rfqs = sent_rfqs.count()

        context = {
            'searched': searched, 
            'replied_rfq_queryset': replied_rfq_queryset,
            'total_replied_rfq': total_replied_rfq,
            'sent_rfqs': sent_rfqs,
            'total_sent_rfqs': total_sent_rfqs
        }
        return render(request, 'solicitations/procurements/searched_replied.html', context)
    else:
        return render(request, 'solicitations/procurements/replied_rfq.html')

##view to delete Replied RFQ
def delete_replied_rfq(request,rfq):
    delete_replied_rfq = RFQReply.objects.get(pk=rfq)
    delete_replied_rfq.delete()
    return redirect('solicitations:replied-rfq')

##########################  OEM RELATED VIEWS  ###############################

## view to show all active oems
def active_oems(request):
    # Filter OEMs related to the user and are not disabled
    oems = OEM.objects.filter(oemuser__user=request.user, oemuser__is_disabled=False)

    # Filter OEMs related to the user and are disabled
    disabled_oems = OEM.objects.filter(oemuser__user=request.user, oemuser__is_disabled=True)

    # Count total OEMs for the user that are not disabled
    total_oems = oems.count()

    # Context to pass to the template
    context = {
        'oems': oems,
        'total_oems': total_oems,
        'disabled_oems': disabled_oems,
    }
    return render(request, 'solicitations/oems/active_oems.html', context)


## view to show oem detail page
def oem_detail(request, oem):
    # Fetch the specific OEM object using the primary key
    oem = get_object_or_404(OEM, pk=oem)

    # Get all OEMUser associations for this OEM
    oem_users = OEMUser.objects.filter(oem=oem)

    # Pass the data to the template
    context = {'oem': oem, 'oem_users': oem_users}
    return render(request, 'solicitations/oems/oem_detail.html', context)

## view to search for OEM
def search_oem(request):
    if request.method == "POST":
        searched = request.POST['search-oem']
        oem = OEM.objects.filter(cage__icontains = searched).first()
        context = {'searched': searched,'oem':oem}
        return render(request,'solicitations/oems/searched_oem.html',context)
    else:
        return render(request,'solicitations/oems/all_oems.html')
    
## view to show all disabled oems
def disabled_oems(request):
    oems = OEM.objects.filter(oemuser__user=request.user, oemuser__is_disabled=False)
    disabled_oems = OEMUser.objects.filter(Q(user = request.user) & Q(is_disabled = True))
    context = {'disabled_oems':disabled_oems,'oems':oems}
    return render(request,'solicitations/oems/disabled_oems.html',context)

## view to disable a particular oem
def disable_oem(request):
    if request.method == 'POST':
        oem = request.POST.get('oem')
        reason = request.POST.get('reason')

        oem_user = get_object_or_404(OEMUser, oem=oem, user=request.user)
        oem_user.is_disabled = True
        oem_user.reason = reason
        oem_user.save()

        messages.success(request, f"OEM {oem_user.oem.name} has been disabled.")
        return redirect('solicitations:active-oems')

    return HttpResponseForbidden("Invalid request")

## view to enable a particular oem
def enable_oem(request, oem_id):
    if request.method == "POST":
        # Fetch the DisabledOEM object
        enable_oem = get_object_or_404(OEMUser, id=oem_id)

        # Enable the OEM
        enable_oem.is_disabled = False 
        enable_oem.save()

        # Clear the reason
        enable_oem.reason = ""
        enable_oem.save()

        # Add a success message
        messages.success(request, f"OEM has been successfully enabled.")

        # Redirect to the same page 
        return redirect('solicitations:disabled-oems')  
    else:
        # Handle non-POST requests (optional)
        return redirect('solicitations:disabled-oems') 


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

        # Serialize the data
        solicitation_data = [
            {
                "id": sol.id,
                "cage": sol.cage,
                "item_name": sol.item_name,
                "quantity": sol.quantity,
                "part_number": sol.part_number,
                "NSN": sol.NSN,
            }
            for sol in solicitations
        ]

        # Debugging: Print the serialized data
        print(f"Solicitation data: {solicitation_data}")

        # Get the logged-in user
        logged_in_user = request.user  # Assuming CustomUser model for logged-in user

        user_data = {
            "username": logged_in_user.username,
            "email": logged_in_user.email,
            "phone": getattr(logged_in_user, "phone", None),
            "address": getattr(logged_in_user, "address", None),
            "companyName": getattr(logged_in_user, "companyName", None),
            "logo": logged_in_user.logo.url if hasattr(logged_in_user, "logo") and logged_in_user.logo else None,
        }

        # Serialize combined user and solicitation data
        combined_data = {
            "user_data": user_data,
            "solicitations": solicitation_data,
        }

        # Debugging: Print combined data
        print(f"Combined data: {json.dumps(combined_data, indent=2)}")

        # Run the external script with the serialized data
        python_exec = r"D:\projects\GilTech\RFQ\gilenv\Scripts\python.exe"
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

