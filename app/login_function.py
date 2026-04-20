from django.contrib.auth.models import User
from django.contrib import auth
import requests
import la_tool.env as env
from la_tool_admin.models import Profile


def login(username, password, request):
    print(f"Attempting to authenticate user: {username}")
    user = auth.authenticate(request, username=username, password=password)
    if user is not None:
        return user

    print(f"User {username} not found locally, trying Divera login.")
    return divera_login(username, password, request)


def divera_login(username, password, request):
    try:
        auth_response = requests.post(
            'https://www.divera247.com/api/v2/auth/login',
            json={
                "Login": {
                    "username": username,
                    "password": password
                }
            },
            timeout=10
        )
    except requests.RequestException:
        request.session['login_error'] = 'Divera ist aktuell nicht erreichbar.'
        return None

    if auth_response.status_code != 200:
        print(f"Error logging in to Divera: {auth_response.status_code}")
        request.session['login_error'] = 'Divera-Login fehlgeschlagen.'
        return None

    try:
        auth_data = auth_response.json()
    except ValueError:
        request.session['login_error'] = 'Ungültige Antwort von Divera beim Login.'
        return None

    if auth_data['success'] != True:
        print(f"Divera login failed")
        request.session['login_error'] = 'Ungültige DIVERA Zugangsdaten.'
        return None

    access_token = auth_data.get('data', {}).get(
        'user', {}).get('access_token')
    if not access_token:
        request.session['login_error'] = 'Kein Divera Access Token erhalten.'
        return None

    print(f"Divera Access Token: {access_token}")

    try:
        data_response = requests.get(
            f'https://app.divera247.com/api/v2/pull/all?accesskey={access_token}',
            # timeout=10
        )
    except requests.RequestException:
        request.session['login_error'] = 'Divera-Benutzerdaten konnten nicht geladen werden.'
        return None
    print(f"Divera Data Response Status: {data_response.status_code}")
    if data_response.status_code != 200:
        print(f"Error pulling Divera user data: {data_response.status_code}")
        request.session['login_error'] = 'Divera-Benutzerdaten konnten nicht geladen werden.'
        return None

    try:
        data = data_response.json()
    except ValueError:
        request.session['login_error'] = 'Ungültige Benutzerdaten von Divera erhalten.'
        return None
    ucr_data = data.get('data', {}).get('ucr', {})
    ucr_items = ucr_data.values() if isinstance(ucr_data, dict) else ucr_data
    firstname = data.get('data', {}).get('user', {}).get('firstname', '')
    lastname = data.get('data', {}).get('user', {}).get('lastname', '')
    expected_site_id = str(env.DIVERA_Site_ID)

    for item in ucr_items:
        print(ucr_items)
        if not isinstance(item, dict):
            continue
        if str(item.get('cluster_id')) == expected_site_id:
            user, _ = User.objects.get_or_create(username=username)
            user.email = username
            user.set_password(password)
            user.first_name = firstname
            user.last_name = lastname
            user.save()

            profile, _ = Profile.objects.get_or_create(user=user)

            profile.divera_api_key = access_token
            # profile.divera_ucr = item.get('id')
            profile.save()
            if 'login_error' in request.session:
                del request.session['login_error']
            return user

    request.session['login_error'] = 'Du bist nicht dem konfigurierten DIVERA Standort zugeordnet.'

    return None
