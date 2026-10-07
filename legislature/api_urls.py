from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .api_views import ParliamentarianViewSet, PartyViewSet, ProjectViewSet, ThemeViewSet, VotingViewSet, dashboard

router = DefaultRouter()
router.register("parliamentarians", ParliamentarianViewSet)
router.register("parties", PartyViewSet)
router.register("projects", ProjectViewSet)
router.register("themes", ThemeViewSet)
router.register("votings", VotingViewSet)

urlpatterns = [path("", include(router.urls)), path("dashboard/", dashboard)]
