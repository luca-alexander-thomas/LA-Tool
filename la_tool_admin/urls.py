from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='admin_index'),

    # Import
    path('import/', views.admin_import_questions, name='admin_import_questions'),
    path('import/example/<str:fmt>/', views.admin_import_example, name='admin_import_example'),

    # Fragenkatalog
    path('catalog/', views.admin_catalog_list, name='admin_catalog'),
    path('catalog/create/', views.admin_catalog_create, name='admin_catalog_create'),
    path('catalog/<int:catalog_id>/', views.admin_catalog_detail, name='admin_catalog_detail'),
    path('catalog/<int:catalog_id>/update/', views.admin_catalog_update, name='admin_catalog_update'),
    path('catalog/<int:catalog_id>/delete/', views.admin_catalog_delete, name='admin_catalog_delete'),

    # Theoriefragen
    path('catalog/<int:catalog_id>/theory/create/', views.admin_theory_create, name='admin_theory_create'),
    path('catalog/<int:catalog_id>/theory/<int:q_id>/', views.admin_theory_edit, name='admin_theory_edit'),
    path('catalog/<int:catalog_id>/theory/<int:q_id>/delete/', views.admin_theory_delete, name='admin_theory_delete'),

    # Praktische Aufgaben
    path('catalog/<int:catalog_id>/practical/create/', views.admin_practical_create, name='admin_practical_create'),
    path('catalog/<int:catalog_id>/practical/<int:q_id>/', views.admin_practical_edit, name='admin_practical_edit'),
    path('catalog/<int:catalog_id>/practical/<int:q_id>/delete/', views.admin_practical_delete, name='admin_practical_delete'),

    # Gruppenaufgaben
    path('catalog/<int:catalog_id>/group/create/', views.admin_group_create, name='admin_group_create'),
    path('catalog/<int:catalog_id>/group/<int:q_id>/', views.admin_group_edit, name='admin_group_edit'),
    path('catalog/<int:catalog_id>/group/<int:q_id>/delete/', views.admin_group_delete, name='admin_group_delete'),

    # Nutzerverwaltung
    path('users/', views.admin_users, name='admin_users'),

    # Prüfungen
    path('exam/', views.admin_exam_list, name='admin_exam_list'),
    path('exam/create/', views.admin_exam_create, name='admin_exam_create'),
    path('exam/<int:exam_id>/', views.admin_exam_edit, name='admin_exam_edit'),
    path('exam/<int:exam_id>/delete/', views.admin_exam_delete, name='admin_exam_delete'),
    path('exam/<int:exam_id>/toggle/<str:field>/', views.admin_exam_toggle, name='admin_exam_toggle'),
    path('exam/<int:exam_id>/results/', views.admin_exam_results, name='admin_exam_results'),
    path('exam/<int:exam_id>/results/<int:result_id>/', views.admin_exam_result_user, name='admin_exam_result_user'),
    path('exam/<int:exam_id>/results/<int:result_id>/release/', views.admin_exam_result_release, name='admin_exam_result_release'),

    # Einstellungen
    path('settings/', views.admin_settings, name='admin_settings'),

    # LA-Stufen
    path('stufen/', views.admin_level_list, name='admin_level_list'),
    path('stufen/erstellen/', views.admin_level_create, name='admin_level_create'),
    path('stufen/<int:level_id>/', views.admin_level_edit, name='admin_level_edit'),
    path('stufen/<int:level_id>/loeschen/', views.admin_level_delete, name='admin_level_delete'),

    # Automatische Gruppen
    path('autogruppen/', views.admin_autogroup_list, name='admin_autogroup_list'),
    path('autogruppen/erstellen/', views.admin_autogroup_create, name='admin_autogroup_create'),
    path('autogruppen/<int:group_id>/', views.admin_autogroup_edit, name='admin_autogroup_edit'),
    path('autogruppen/<int:group_id>/loeschen/', views.admin_autogroup_delete, name='admin_autogroup_delete'),

    # Dienste
    path('work/', views.admin_work_list, name='admin_work_list'),
    path('work/create/', views.admin_work_create, name='admin_work_create'),
    path('work/sync/', views.admin_work_sync, name='admin_work_sync'),
    path('work/<int:work_id>/', views.admin_work_edit, name='admin_work_edit'),
    path('work/<int:work_id>/delete/', views.admin_work_delete, name='admin_work_delete'),

    # Entwurf-Toggle (generisch für alle Modelle)
    path('draft/<str:model>/<int:pk>/toggle/', views.admin_draft_toggle, name='admin_draft_toggle'),

    # Datei-Bestätigung bei Duplikaten
    path('file-confirm/', views.admin_file_confirm, name='admin_file_confirm'),

]
