from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('api/process-story/', views.process_story, name='process_story'),
    path('contact/<int:contact_id>/stories/', views.contact_stories_view, name='contact_stories'),
    path('campaign/<int:campaign_id>/', views.campaign_detail, name='campaign_detail'),
    path('campaign/<int:campaign_id>/export/', views.campaign_export_excel, name='campaign_export_excel'),
    path("campaigns/", views.campaign_list, name="campaign_list"),
    path("contacts/", views.contact_list, name="contact_list"),
]
