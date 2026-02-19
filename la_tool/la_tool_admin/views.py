from django.template import loader
from django.shortcuts import render, redirect
from django.contrib import auth
from django.conf import settings


def index(request):
    user = request.user
    if not user.is_authenticated:
        return redirect('login')  # Nicht angemeldet, weiterleiten zur Anmeldung
    else:
        return render(request, "admin.html",{"user": user, "settings": settings})


def login(request):
    if request.user.is_authenticated:
        return redirect('index')  # Bereits angemeldet, weiterleiten zum Index
    if request.method == "POST":
        # Hier würden Sie die Anmeldeinformationen überprüfen
        username = request.POST.get("username")
        password = request.POST.get("password")
        # Beispiel: Überprüfen Sie die Anmeldeinformationen (dies ist nur ein Platzhalter)
        
        auth_user = auth.authenticate(request, username=username, password=password)
        if auth_user is not None:
            auth.login(request, auth_user)
            if auth_user.is_superuser:
                return redirect('admin_index')   # Erfolgreiche Anmeldung
            else:
                return redirect('home')   # Erfolgreiche Anmeldung, aber kein Admin

        else:
            return render(request, "login.html", {"error": "Ungültige Anmeldeinformationen"})
    return render(request, "login.html")

def profile(request):
    if not request.user.is_authenticated:
        return redirect('login')  # Nicht angemeldet, weiterleiten zur Anmeldung
    if request.method == "GET": 
        user = request.user

    return render(request, "profile.html", {"user": user})
