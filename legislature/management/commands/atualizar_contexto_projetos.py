import requests
from django.core.management.base import BaseCommand, CommandError

from legislature.models import Project
from services.camara import CamaraAPI, refresh_project_context


class Command(BaseCommand):
    help = "Completa ementa detalhada, assuntos e situação dos projetos já votados."

    def add_arguments(self, parser):
        parser.add_argument("--todos", action="store_true", help="Reprocessa inclusive os que já têm detalhes.")

    def handle(self, *args, **options):
        queryset = Project.objects.filter(votings__votes__isnull=False, is_mock=False).distinct()
        if not options["todos"]:
            queryset = queryset.filter(situation="")
        api = CamaraAPI()
        updated = 0
        for project in queryset:
            try:
                refresh_project_context(project, api)
            except requests.RequestException as error:
                raise CommandError(f"Fonte oficial indisponível: {error}") from error
            updated += 1
        self.stdout.write(self.style.SUCCESS(f"{updated} projetos com contexto detalhado atualizado."))
