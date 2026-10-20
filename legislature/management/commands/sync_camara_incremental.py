import requests
from django.core.management.base import BaseCommand, CommandError

from services.camara import sync_camara_incremental


class Command(BaseCommand):
    help = "Atualiza somente parlamentares, projetos, votações e despesas após a carga histórica."

    def handle(self, *args, **options):
        try:
            totals = sync_camara_incremental()
        except (requests.RequestException, ValueError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            self.style.SUCCESS(
                "Atualização incremental concluída: "
                f"{totals['projects']} projetos, "
                f"{totals['votings']} votações e "
                f"{totals['expenses']} despesas."
            )
        )
