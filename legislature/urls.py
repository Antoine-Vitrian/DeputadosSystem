from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView, TemplateView

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("parlamentares/", views.parliamentarian_list, name="parliamentarian-list"),
    path("parlamentares/<int:pk>/", views.parliamentarian_detail, name="parliamentarian-detail"),
    path("votacoes/", views.voting_list, name="voting-list"),
    path("votacoes/<int:pk>/", views.voting_detail, name="voting-detail"),
    path("projetos/", RedirectView.as_view(pattern_name="voting-list", query_string=True, permanent=False)),
    path("projetos/<int:pk>/", views.project_detail, name="project-detail"),
    path("pesquisa/", views.search, name="search"),
    path("entenda/", views.guide, name="guide"),
    path("entrar/", TemplateView.as_view(template_name="login.html"), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
]
