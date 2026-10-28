from datetime import timedelta

from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.models import Levels, Questions_Catalogs, Questions_Practical, Work


def grant(user, *codenames):
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label='app', codename__in=codenames))


class AdminPermissionTests(TestCase):
    """Zugriffsregeln des Admin-Bereichs: Login, 'access_admin' und Einzelrechte."""

    def setUp(self):
        self.member = User.objects.create_user('member', password='pw')
        self.viewer = User.objects.create_user('viewer', password='pw')
        grant(self.viewer, 'access_admin')
        self.user_manager = User.objects.create_user('usermanager', password='pw')
        grant(self.user_manager, 'access_admin', 'manage_users')
        self.other_admin = User.objects.create_user('otheradmin', password='pw')
        grant(self.other_admin, 'access_admin')

    def login(self, user):
        self.client.force_login(user)
        session = self.client.session
        session['first_run_done'] = True
        session.save()

    def test_anonymous_is_sent_to_login_with_next(self):
        for name in ('admin_index', 'admin_catalog_create', 'admin_users'):
            url = reverse(name)
            response = self.client.get(url)
            self.assertRedirects(response, f"{reverse('login')}?next={url}", fetch_redirect_response=False)

    def test_member_without_admin_access_gets_403_page(self):
        self.login(self.member)
        response = self.client.get(reverse('admin_index'))
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, '403.html')
        self.assertContains(response, 'Admin-Bereich zugreifen', status_code=403)

    def test_viewer_sees_overview_but_not_protected_pages(self):
        self.login(self.viewer)
        self.assertEqual(self.client.get(reverse('admin_index')).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin_catalog')).status_code, 200)
        for name in ('admin_catalog_create', 'admin_users', 'admin_settings', 'admin_exam_create'):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 403, name)

    def test_viewer_does_not_see_links_to_protected_pages(self):
        self.login(self.viewer)
        html = self.client.get(reverse('admin_catalog')).content.decode()
        self.assertNotIn(reverse('admin_catalog_create'), html)
        self.assertNotIn(reverse('admin_users'), html)
        self.assertNotIn(reverse('admin_settings'), html)

    def test_user_manager_cannot_grant_permissions(self):
        self.login(self.user_manager)
        response = self.client.post(reverse('admin_users'), {
            'user_id': self.member.pk, 'action': 'toggle_perm', 'perm_codename': 'manage_users',
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.get(pk=self.member.pk).has_perm('app.manage_users'))

    def test_user_manager_cannot_reset_admin_password(self):
        self.login(self.user_manager)
        response = self.client.post(reverse('admin_users'), {'user_id': self.other_admin.pk, 'action': 'reset_password'})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(User.objects.get(pk=self.other_admin.pk).check_password('pw'))

    def test_user_manager_can_reset_member_password(self):
        self.login(self.user_manager)
        response = self.client.post(reverse('admin_users'), {'user_id': self.member.pk, 'action': 'reset_password'})
        self.assertRedirects(response, reverse('admin_users'), fetch_redirect_response=False)
        self.assertFalse(User.objects.get(pk=self.member.pk).check_password('pw'))


class AppAccessTests(TestCase):
    """Sichtbarkeit von Diensten und Aufgaben sowie Login-Rücksprung."""

    def setUp(self):
        self.user = User.objects.create_user('jugend', password='pw')
        level = Levels.objects.create(name='Teststufe', slug='teststufe', order=99)
        catalog = Questions_Catalogs.objects.create(title='Katalog', short_title='K', level=level)
        self.task = Questions_Practical.objects.create(question='Knoten', catalog=catalog)
        self.draft_task = Questions_Practical.objects.create(question='Entwurf', catalog=catalog, is_draft=True)
        start = timezone.now() + timedelta(days=1)
        self.work = Work.objects.create(title='Dienst', date=start)
        self.draft_work = Work.objects.create(title='Entwurf', date=start, is_draft=True)
        self.group_work = Work.objects.create(title='Fremde Gruppe', date=start)
        self.group_work.groups.add(Group.objects.create(name='Andere'))

    def login(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['first_run_done'] = True
        session.save()

    def test_work_detail_hides_drafts_and_other_groups(self):
        self.login()
        self.assertEqual(self.client.get(reverse('work_detail', args=[self.work.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('work_detail', args=[self.draft_work.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('work_detail', args=[self.group_work.pk])).status_code, 404)

    def test_practical_detail_hides_drafts(self):
        self.assertEqual(self.client.get(reverse('practical_detail', args=[self.task.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('practical_detail', args=[self.draft_task.pk])).status_code, 404)

    def test_login_redirects_back_to_requested_page(self):
        url = reverse('work')
        response = self.client.get(url)
        self.assertRedirects(response, f"{reverse('login')}?next={url}", fetch_redirect_response=False)

    def test_login_ignores_foreign_next(self):
        self.login()
        response = self.client.get(reverse('login') + '?next=https://evil.example/')
        self.assertRedirects(response, reverse('home'), fetch_redirect_response=False)
