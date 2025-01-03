import json
import os
from django.shortcuts import get_object_or_404, redirect, render
from django.http import HttpResponseNotFound, JsonResponse
from accounts.models import CustomUser
from . models import RFQ, RFQReply, Solicitation,OEM
from django.contrib import messages
import subprocess
from . forms import UserRegistrationForm,RFQReplyForm
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
    client = CustomUser.objects.get(pk = client)
    context = {'client':client}
    return render(request,'solicitations/clients/details.html',context)

## view to show all sent rfqs
def sent_rfq(request):
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
    user=request.user
    print(user.username)
    rfq_unique_id = request.GET.get('rfq_unique_id')  # Get the unique_id from query params
    rfq = get_object_or_404(RFQ, unique_id=rfq_unique_id)  # Fetch RFQ by unique_id

    solicitation = rfq.solicitation

    if request.method == 'POST':
        form = RFQReplyForm(request.POST, request.FILES)
        if form.is_valid():
            rfq_reply = form.save(commit=False)
            rfq_reply.rfq = rfq  # Get the unsaved House instance
            rfq_reply.rfq_creator = request.user # Associate the reply with the RFQ
            rfq_reply.save()
            messages.success(request, "Reply submitted successfully!")
            return redirect('accounts:login-user')
    else:
        form = RFQReplyForm()

    return render(request, 'solicitations/procurements/rfq_reply.html', {'form': form, 'rfq': rfq,'solicitatio':solicitation})


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

## view to show all oems
def all_oems(request):
    oems = OEM.objects.all()
    total_oems = oems.count()
    context = {'oems':oems,'total_oems':total_oems}
    return render(request,'solicitations/oems/all_oems.html',context)

## view to show eom detail page
def oem_detail(request,oem):
    oem = OEM.objects.get(pk = oem)
    context = {'oem':oem}
    return render(request,'solicitations/oems/oem_detail.html',context)

def send_rfqs(request):
    if request.method == "POST":
        try:
            # Path to Python executable
            python_exec = r"D:\projects\GilTech\RFQ\gilenv\Scripts\python.exe"
            # Path to the script
            script_path = os.path.join(os.getcwd(), "infoExtractorSendRfq.py")
            
            # Get the logged-in user
            logged_in_user = CustomUser.objects.get(username=request.user.username)
            
            # Serialize the user data to JSON
            user_data = {
                "username": logged_in_user.username,
                "email": logged_in_user.email,
                "phone": logged_in_user.phone,
                "address": logged_in_user.address,
                "companyName": logged_in_user.companyName,
                "logo": logged_in_user.logo.url if logged_in_user.logo else None,
            }

            # Serialize user data to a JSON string
            serialized_data = json.dumps(user_data)

            print(f"Serialized user_data: {serialized_data}")  # Debugging

            # Run the script asynchronously using subprocess
            result = subprocess.Popen(
                [python_exec, script_path, serialized_data],  # Pass JSON string as argument
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # Check the output from the script
            stdout, stderr = result.communicate()

            if result.returncode != 0:
                error_message = f"Subprocess failed with error: {stderr}"
                print(error_message)  # Log the error for debugging
                return JsonResponse({"error": error_message}, status=500)

            print(f"Subprocess output: {stdout}")  # Log the output for debugging

            # Send output to frontend
            return JsonResponse({"message": stdout}, status=200)
            
        except Exception as e:
            error_message = f"Unexpected error: {str(e)}"
            print(error_message)  # Log unexpected errors
            return JsonResponse({"error": error_message}, status=500)

    return JsonResponse({"error": "Invalid request method"}, status=405)

