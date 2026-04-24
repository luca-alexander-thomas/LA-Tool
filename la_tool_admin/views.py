from django.template import loader
from django.shortcuts import render, redirect
from django.contrib import auth
from django.conf import settings


def index(request):
    user = request.user
    if not user.is_authenticated:
        # Nicht angemeldet, weiterleiten zur Anmeldung
        return redirect('login')
    else:
        return render(request, "admin-home.html", {"user": user, "settings": settings})


def login(request):
    if request.user.is_authenticated:
        return redirect('index')  # Bereits angemeldet, weiterleiten zum Index
    if request.method == "POST":
        # Hier würden Sie die Anmeldeinformationen überprüfen
        username = request.POST.get("username")
        password = request.POST.get("password")
        # Beispiel: Überprüfen Sie die Anmeldeinformationen (dies ist nur ein Platzhalter)

        auth_user = auth.authenticate(
            request, username=username, password=password)
        if auth_user is not None:
            auth.login(request, auth_user)
            if auth_user.is_superuser:
                return redirect('admin_index')   # Erfolgreiche Anmeldung
            else:
                # Erfolgreiche Anmeldung, aber kein Admin
                return redirect('home')

        else:
            return render(request, "login.html", {"error": "Ungültige Anmeldeinformationen"})
    return render(request, "login.html")

def admin_users(request):
    if not request.user.is_authenticated:
        return redirect('login')
    return render(request, "admin-users.html", {"user": request.user})

def admin_catalog(request,vtype=None):
    if request.method == "GET":
        if not request.user.is_authenticated:
            return redirect('login')
        if vtype == 'edit':
            return render(request, "admin-catalog-detail.html", {"user": request.user})
        elif vtype == None:
            return render(request, "admin-catalog.html", {"user": request.user})
    return redirect('login')

def admin_exam(request, vtype=None):
    if request.method == "GET":
        if not request.user.is_authenticated:
            return redirect('login')
        if vtype == 'edit':
            return render(request, "admin-exams-edit-create.html", {"user": request.user})
        elif vtype == 'summary':
            return render(request, "admin-exam-summary.html", {"user": request.user})
        elif vtype == 'summary-user':
            return render(request, "admin-exam-summary-user.html", {"user": request.user})
        elif vtype == None:
            return render(request, "admin-exams.html", {"user": request.user})
    return redirect('login')

def admin_work(request, vtype=None):
    if request.method == "GET":
        if not request.user.is_authenticated:
            return redirect('login')
        if vtype == 'edit':
            return render(request, "admin-work-edit-create.html", {"user": request.user})
        if vtype == 'detail':
            return render(request, "admin-work-edit-create.html", {"user": request.user})
        elif vtype == None:
            return render(request, "admin-work.html", {"user": request.user})
    return redirect('login')