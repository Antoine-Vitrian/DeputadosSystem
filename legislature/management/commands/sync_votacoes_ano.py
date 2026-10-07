from datetime import date

import requests
from django.core.management.base import BaseCommand, CommandError

from services.camara import sync_nominal_votings_year


class Command(BaseCommand):
    help = "Importa todas as votações nominais e os projetos relacionados de um ano."

    def add_arguments(self, parser):
        parser.add_argument("--ano", type=int, default=date.today().year)
        parser.add_argument("--max-pages", type=int, default=None)

    def handle(self, *args, **options):
        try:
            totals = sync_nominal_votings_year(
                options["ano"],
                max_pages=options["max_pages"],
            )
        except requests.RequestException as error:
            raise CommandError(f"Fonte oficial indisponível: {error}") from error
        self.stdout.write(
            self.style.SUCCESS(
                f"{totals['year']}: {totals['projects']} projetos com votação nominal, "
                f"{totals['votings']} votações encontradas em {totals['pages']} páginas "
                f"({totals['scanned']} registros examinados)."
            )
        )
