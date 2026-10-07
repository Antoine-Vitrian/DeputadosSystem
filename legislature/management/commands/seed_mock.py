from django.core.management.base import BaseCommand
from legislature.models import DataSource, Party, Parliamentarian, Project, Theme, LegislativeLevel


class Command(BaseCommand):
    help = "Cria dados de demonstração explicitamente marcados como MOCK."

    def handle(self, *args, **options):
        source, _ = DataSource.objects.get_or_create(name="Dados de demonstração MOCK", defaults={"url": "https://example.invalid/mock", "identifier": "mock"})
        party, _ = Party.objects.get_or_create(acronym="MOCK", defaults={"name": "Partido de demonstração MOCK"})
        person, _ = Parliamentarian.objects.update_or_create(external_id="mock-1", defaults={"name": "Parlamentar de demonstração", "role": "Deputado federal", "state": "SP", "level": LegislativeLevel.FEDERAL, "party": party, "source": source, "is_mock": True})
        theme, _ = Theme.objects.get_or_create(name="Dados públicos")
        project, _ = Project.objects.update_or_create(external_id="mock-project-1", defaults={"code": "MOCK 001/2026", "title": "Projeto de demonstração do Radar Legislativo", "description": "Registro de teste, sem correspondência com uma proposição real.", "level": LegislativeLevel.FEDERAL, "author": person, "source": source, "is_mock": True})
        project.themes.add(theme)
        self.stdout.write(self.style.SUCCESS("Dados MOCK criados e identificados como teste."))
