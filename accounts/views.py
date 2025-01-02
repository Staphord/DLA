from django.shortcuts import render,redirect
from django.contrib.auth import login,authenticate,logout
from django.contrib import messages

# Create your views here.

## view to log in a user
def login_user(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            #redirect
            return redirect('solicitations:home')

        else:
            #redirect
            messages.success(request,'There was an error login in, Try again latter!')
            return redirect('accounts:login-user')
    
    else:
        #
        return render(request,'accounts/login.html')

## view to log out a user
def logout_user(request):
    logout(request)
    return redirect('accounts:login-user')
