from django.db.models import Count, Q
from rest_framework import viewsets
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import Parliamentarian, Party, Project, Theme, Vote, Voting
from .serializers import ParliamentarianSerializer, PartySerializer, ProjectSerializer, ThemeSerializer, VotingSerializer


class ParliamentarianViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Parliamentarian.objects.select_related("party").all()
    serializer_class = ParliamentarianSerializer
    filterset_fields = ["level", "state", "party", "is_mock"]
    search_fields = ["name", "civil_name", "party__name", "party__acronym"]
    ordering_fields = ["name"]


class PartyViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Party.objects.all()
    serializer_class = PartySerializer
    search_fields = ["name", "acronym"]


class ProjectViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Project.objects.filter(Q(presented_at__isnull=False) | Q(votings__isnull=False)).distinct().select_related("author", "source").prefetch_related("themes").all()
    serializer_class = ProjectSerializer
    filterset_fields = ["level", "status", "author", "author__party", "themes", "is_mock"]
    search_fields = ["code", "title", "description"]
    ordering_fields = ["presented_at", "title"]


class ThemeViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Theme.objects.all()
    serializer_class = ThemeSerializer
    search_fields = ["name"]


class VotingViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Voting.objects.prefetch_related("votes__parliamentarian").all()
    serializer_class = VotingSerializer
    filterset_fields = ["level", "project"]
    search_fields = ["title", "result"]
    ordering_fields = ["voted_at"]


@api_view(["GET"])
def dashboard(request):
    projects = Project.objects.all()
    level = request.query_params.get("level")
    if level:
        projects = projects.filter(level=level)
    votes = Vote.objects.filter(**({"voting__level": level} if level else {}))
    vote_counts = {row["choice"]: row["total"] for row in votes.values("choice").annotate(total=Count("id"))}
    return Response({
        "projects": projects.count(),
        "approved_projects": projects.filter(status=Project.Status.APPROVED).count(),
        "rejected_projects": projects.filter(status=Project.Status.REJECTED).count(),
        "in_progress_projects": projects.filter(status=Project.Status.IN_PROGRESS).count(),
        "parliamentarians": Parliamentarian.objects.filter(is_mock=False, is_active=True, **({"level": level} if level else {})).count(),
        "votings": Voting.objects.filter(**({"level": level} if level else {})).count(),
        "votes": vote_counts,
        "projects_by_theme": list(Theme.objects.annotate(total=Count("projects", filter=__import__("django.db.models", fromlist=["Q"]).Q(projects__in=projects))).values("name", "total")),
    })
