from datetime import date
import requests
from django.core.management.base import BaseCommand, CommandError
from services.camara import CamaraAPI, source, sync_expenses, sync_recent_legislative_data


class Command(BaseCommand):
    help = "Atualiza listas recentes; detalhes, votos e despesas são carregados sob demanda."

    def add_arguments(self, parser):
        parser.add_argument("--desde", type=int, default=date.today().year)
        parser.add_argument("--ate", type=int, default=date.today().year)
        parser.add_argument("--max-pages", type=int, default=5)
        parser.add_argument("--com-despesas", action="store_true")

    def handle(self, *args, **options):
        try:
            totals = sync_recent_legislative_data(page_count=options["max_pages"])
            expenses = sync_expenses(CamaraAPI(), source(), options["desde"], options["ate"]) if options["com_despesas"] else 0
            self.stdout.write(self.style.SUCCESS(f"Atualização concluída: {totals['deputies']} deputados ativos, {totals['projects']} projetos com voto nominal, {totals['votings']} votações nominais encontradas após examinar {totals['scanned']} registros e {expenses} despesas."))
        except requests.RequestException as error:
            raise CommandError(f"Fonte oficial indisponível: {error}") from error
