import requests
from django.core.management.base import BaseCommand, CommandError

from services.camara import CamaraAPI, source, sync_deputies


class Command(BaseCommand):
    help = "Atualiza a lista de parlamentares federais para busca local rápida."

    def handle(self, *args, **options):
        try:
            total = sync_deputies(CamaraAPI(), source(), 0, 0)
        except requests.RequestException as error:
            raise CommandError(f"Fonte oficial indisponível: {error}") from error
        self.stdout.write(self.style.SUCCESS(f"Lista de parlamentares atualizada: {total} deputados."))
