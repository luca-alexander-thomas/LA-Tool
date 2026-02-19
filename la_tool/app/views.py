from django.shortcuts import render, redirect
from django.contrib import auth
from django.contrib.auth.models import User, Group
from django.conf import settings
import msal
import requests
import uuid
import json

def index(request):
    return render(request, "home.html")

def login(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")
        
        auth_user = auth.authenticate(request, username=username, password=password)
        if auth_user is not None:
            auth.login(request, auth_user)
            return redirect('home')
        else:
            return render(request, "login.html", {"error": "Ungültige Anmeldeinformationen"})
    return render(request, "login.html")

def profile(request):
    if not request.user.is_authenticated:
        return redirect('login')
    return render(request, "profile.html", {"user": request.user})

def logout(request):
    auth.logout(request)
    return redirect('home')

def sync_user_groups(user, access_token):
    """Synchronisiert Azure AD Gruppenmitgliedschaften zu Django Groups"""
    try:
        # Gruppenmitgliedschaften von Microsoft Graph abrufen
        headers = {'Authorization': f'Bearer {access_token}'}
        
        # Versuche zuerst mit $filter
        # memberOf abrufen (nur Gruppen, keine rollen)
        graph_url = 'https://graph.microsoft.com/v1.0/me/memberOf'
        
        graph_response = requests.get(graph_url, headers=headers)
        
        if graph_response.status_code != 200:
            error_detail = graph_response.json() if graph_response.text else "Keine Details"
            print(f"Fehler beim Abrufen der Gruppen: {graph_response.status_code}")
            print(f"Response: {error_detail}")
            return
        
        groups_data = graph_response.json()
        azure_group_ids = set()
        
        # Alle Gruppen die der User in Azure hat - filtere nur Groups (nicht Roles)
        for item in groups_data.get('value', []):
            # Überprüfe ob es sich um eine Gruppe handelt (hat @odata.type)
            if '@odata.type' in item and 'microsoft.graph.group' in item['@odata.type']:
                group_id = item.get('id')
                if group_id and group_id in getattr(settings, 'AZURE_GROUPS_MAPPING', {}):
                    azure_group_ids.add(group_id)
        
        # Django Groups synchronisieren
        django_groups_to_assign = set()
        
        for azure_group_id in azure_group_ids:
            group_name = settings.AZURE_GROUPS_MAPPING[azure_group_id]
            
            # Django Group erstellen falls nicht vorhanden
            django_group, created = Group.objects.get_or_create(name=group_name)
            django_groups_to_assign.add(django_group)
        
        # Aktuelle Gruppen des Users - als QuerySet behalten
        current_groups = user.groups.all()
        
        # Gruppen aus AZURE_GROUPS_MAPPING die der User aktuell hat
        mapped_group_names = set(settings.AZURE_GROUPS_MAPPING.values())
        groups_to_remove = current_groups.filter(name__in=mapped_group_names).exclude(
            name__in=[g.name for g in django_groups_to_assign]
        )
        
        # Gruppen entfernen
        for group in groups_to_remove:
            user.groups.remove(group)
        
        # Gruppen hinzufügen
        for group in django_groups_to_assign:
            user.groups.add(group)
        
        user.save()
        print(f"User {user.username} Gruppen synchronisiert: {[g.name for g in django_groups_to_assign]}")
        
    except Exception as e:
        print(f"Fehler beim Synchronisieren der Gruppen: {str(e)}")

# Microsoft OAuth Callbacks
def microsoft_login(request):
    """Initiiert den OAuth Login Flow zu Microsoft Entra ID"""
    if request.user.is_authenticated:
        return redirect('home')
    
    # MSAL Client erstellen für Authorization URL (ConfidentialClient mit Secret)
    client = msal.ConfidentialClientApplication(
        settings.MICROSOFT_AUTH_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{settings.MICROSOFT_AUTH_TENANT_ID}",
        client_credential=settings.MICROSOFT_AUTH_CLIENT_SECRET,
    )
    
    # State generieren für CSRF-Protection
    state = str(uuid.uuid4())
    request.session['oauth_state'] = state
    
    # Authorization URL erstellen
    auth_url = client.get_authorization_request_url(
        scopes=['user.read', 'Directory.Read.All'],
        redirect_uri=settings.MICROSOFT_AUTH_REDIRECT_URI,
        state=state,
    )
    
    return redirect(auth_url)

def microsoft_callback(request):
    """Verarbeitet den OAuth Callback von Microsoft Entra ID"""
    # State validieren
    stored_state = request.session.get('oauth_state')
    callback_state = request.GET.get('state')
    
    if not stored_state or stored_state != callback_state:
        return render(request, 'login.html', {'error': 'Sicherheitsfehler: State stimmt nicht überein'})
    
    # Authorization Code abrufen
    code = request.GET.get('code')
    error = request.GET.get('error')
    error_description = request.GET.get('error_description', '')
    
    if error:
        return render(request, 'login.html', {
            'error': f'Microsoft Login fehlgeschlagen: {error_description}'
        })
    
    if not code:
        return render(request, 'login.html', {'error': 'Kein Authorization Code erhalten'})
    
    try:
        # Token mit Authorization Code austauschen (ConfidentialClient mit Secret)
        client = msal.ConfidentialClientApplication(
            settings.MICROSOFT_AUTH_CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{settings.MICROSOFT_AUTH_TENANT_ID}",
            client_credential=settings.MICROSOFT_AUTH_CLIENT_SECRET,
        )
        
        token_result = client.acquire_token_by_authorization_code(
            code=code,
            scopes=['user.read', 'Directory.Read.All'],
            redirect_uri=settings.MICROSOFT_AUTH_REDIRECT_URI,
        )
        
        if 'error' in token_result:
            return render(request, 'login.html', {
                'error': f'Token-Fehler: {token_result.get("error_description", "Unbekannter Fehler")}'
            })
        
        # Access Token aus Antwort holen
        access_token = token_result.get('access_token')
        
        # Microsoft Graph API aufrufen um Benutzerinformationen zu holen
        headers = {'Authorization': f'Bearer {access_token}'}
        graph_response = requests.get(
            'https://graph.microsoft.com/v1.0/me',
            headers=headers
        )
        
        if graph_response.status_code != 200:
            return render(request, 'login.html', {
                'error': 'Fehler beim Abrufen der Benutzerinformationen'
            })
        
        user_info = graph_response.json()
        
        # Benutzer-Identifikation
        microsoft_id = user_info.get('id')
        email = user_info.get('mail') or user_info.get('userPrincipalName')
        first_name = user_info.get('givenName', '')
        last_name = user_info.get('surname', '') or 'User'  # Default-Wert wenn leer
        
        if not email:
            return render(request, 'login.html', {
                'error': 'E-Mail-Adresse konnte nicht abgerufen werden'
            })
        
        # Django User erstellen oder abrufen
        user, created = User.objects.get_or_create(
            username=email,
            defaults={
                'email': email,
                'first_name': first_name,
                'last_name': last_name,
            }
        )
        
        # Gruppenmitgliedschaften synchronisieren
        sync_user_groups(user, access_token)
        
        # Benutzer einloggen
        auth.login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        
        # State aus Session löschen
        if 'oauth_state' in request.session:
            del request.session['oauth_state']
        
        return redirect('home')
        
    except Exception as e:
        return render(request, 'login.html', {
            'error': f'Ein Fehler ist aufgetreten: {str(e)}'
        })
