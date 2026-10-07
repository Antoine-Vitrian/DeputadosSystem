from datetime import date
from django.core.management.base import BaseCommand
from services.camara import CamaraAPI, source, sync_deputies, sync_projects, sync_votings


class Command(BaseCommand):
    help = "Importa deputados e proposições federais oficiais desde um ano."

    def add_arguments(self, parser):
        parser.add_argument("--desde", type=int, default=2023)
        parser.add_argument("--ate", type=int, default=date.today().year)
        parser.add_argument("--max-pages", type=int, default=1)

    def handle(self, *args, **options):
        api = CamaraAPI()
        data_source = source()
        deputies = sync_deputies(api, data_source, options["desde"], options["ate"])
        projects = sync_projects(api, data_source, options["desde"], options["ate"], options["max_pages"])
        votings = sync_votings(api, data_source, options["desde"], options["ate"], options["max_pages"])
        self.stdout.write(self.style.SUCCESS(f"Sincronizados {deputies} deputados federais, {projects} projetos e {votings} votações oficiais."))
