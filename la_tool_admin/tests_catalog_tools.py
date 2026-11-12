"""Katalog-Verwaltung: Sammelaktionen, Anzeige mehrerer richtiger Antworten, Stufe im Import, gemerkte Filter."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from app.models import Levels, Questions_Catalogs, Questions_Practical, Questions_Theory
from .tests import grant


class CatalogToolsTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user('admin')
        grant(self.admin, 'access_admin', 'manage_theory', 'manage_practical')
        self.client.force_login(self.admin)
        self.bronze = Levels.objects.create(name='Bronze', slug='bronze-t', order=90)
        self.silber = Levels.objects.create(name='Silber', slug='silber-t', order=91)
        self.cat = Questions_Catalogs.objects.create(title='Leinen', short_title='L1', level=self.bronze)
        self.other = Questions_Catalogs.objects.create(title='Leinen', short_title='L1', level=self.silber)
        self.q1 = Questions_Theory.objects.create(number='1', question='Q1', catalog=self.cat, answer_text='a',
                                                  answer_choice=['a', 'b', 'c'], answer_correct=['a', 'c'])
        self.q2 = Questions_Theory.objects.create(number='2', question='Q2', catalog=self.cat, answer_text='b',
                                                  answer_choice=['a', 'b'], is_draft=True)

    def bulk(self, action, ids, **extra):
        return self.client.post(reverse('admin_catalog_bulk', args=[self.cat.pk]),
                                {'kind': 'theory', 'action': action, 'ids': [str(i) for i in ids], **extra})

    def test_detail_marks_all_correct_answers(self):
        html = self.client.get(reverse('admin_catalog_detail', args=[self.cat.pk])).content.decode()
        self.assertEqual(html.count('<span class="sr-only">Richtig: </span>a'), 1)  # „a“ nur bei Q1 richtig
        self.assertIn('<span class="sr-only">Richtig: </span>c', html)
        self.assertIn('<span class="sr-only">Richtig: </span>b', html)

    def test_bulk_publish_draft_move_delete(self):
        self.bulk('publish', [self.q1.pk, self.q2.pk])
        self.assertFalse(Questions_Theory.objects.filter(is_draft=True).exists())
        self.bulk('draft', [self.q1.pk])
        self.assertTrue(Questions_Theory.objects.get(pk=self.q1.pk).is_draft)
        response = self.bulk('move', [self.q1.pk], target=self.other.pk)
        self.assertRedirects(response, reverse('admin_catalog_detail', args=[self.cat.pk]) + '?tab=theory',
                             fetch_redirect_response=False)
        self.assertEqual(Questions_Theory.objects.get(pk=self.q1.pk).catalog, self.other)
        self.bulk('delete', [self.q2.pk])
        self.assertFalse(Questions_Theory.objects.filter(pk=self.q2.pk).exists())

    def test_bulk_ignores_foreign_ids_and_needs_permission(self):
        foreign = Questions_Theory.objects.create(question='F', catalog=self.other, answer_text='x', answer_choice=['x'])
        self.bulk('delete', [foreign.pk])
        self.assertTrue(Questions_Theory.objects.filter(pk=foreign.pk).exists())
        viewer = User.objects.create_user('viewer')
        grant(viewer, 'access_admin', 'manage_practical')
        self.client.force_login(viewer)
        self.assertEqual(self.bulk('delete', [self.q1.pk]).status_code, 403)
        self.assertTrue(Questions_Theory.objects.filter(pk=self.q1.pk).exists())

    def test_bulk_practical(self):
        p = Questions_Practical.objects.create(number='P1', question='P', catalog=self.cat, is_draft=True)
        self.client.post(reverse('admin_catalog_bulk', args=[self.cat.pk]),
                         {'kind': 'practical', 'action': 'publish', 'ids': [str(p.pk)]})
        self.assertFalse(Questions_Practical.objects.get(pk=p.pk).is_draft)

    def test_import_select_shows_level(self):
        html = self.client.get(reverse('admin_import_questions')).content.decode()
        self.assertIn('Bronze · L1 – Leinen', html)
        self.assertIn('Silber · L1 – Leinen', html)

    def test_catalog_filters_survive_detail_and_toggle(self):
        grant(self.admin, 'manage_catalogs')
        self.client.get(reverse('admin_catalog'), {'stufe': 'silber-t', 'status': 'live'})
        html = self.client.get(reverse('admin_catalog_detail', args=[self.cat.pk])).content.decode()
        self.assertIn(reverse('admin_catalog') + '?stufe=silber-t&amp;status=live', html)
        response = self.client.post(reverse('admin_draft_toggle', args=['catalog', self.cat.pk]))
        self.assertEqual(response['Location'], reverse('admin_catalog') + '?stufe=silber-t&status=live')
        # Filter zurücksetzen: Liste ohne Parameter vergisst sie
        self.client.get(reverse('admin_catalog'))
        response = self.client.post(reverse('admin_draft_toggle', args=['catalog', self.cat.pk]))
        self.assertEqual(response['Location'], reverse('admin_catalog'))
