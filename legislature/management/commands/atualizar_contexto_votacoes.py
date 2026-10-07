import requests
from django.core.management.base import BaseCommand, CommandError

from legislature.models import Voting
from services.camara import CamaraAPI, refresh_voting_context


class Command(BaseCommand):
    help = "Completa a descrição detalhada das votações já importadas."

    def add_arguments(self, parser):
        parser.add_argument("--todas", action="store_true", help="Reprocessa inclusive as que já têm detalhes.")

    def handle(self, *args, **options):
        queryset = Voting.objects.filter(votes__isnull=False).distinct()
        if not options["todas"]:
            queryset = queryset.filter(procedure="")
        api = CamaraAPI()
        updated = 0
        for voting in queryset:
            try:
                refresh_voting_context(voting, api)
            except requests.RequestException as error:
                raise CommandError(f"Fonte oficial indisponível: {error}") from error
            updated += 1
        self.stdout.write(self.style.SUCCESS(f"{updated} votações com descrição detalhada atualizada."))
