from datetime import date, timedelta

import requests
from django.core.management.base import BaseCommand, CommandError

from legislature.models import NewsArticle
from services.news import sync_daily_news


class Command(BaseCommand):
    help = "Busca notícias políticas e cria o resumo do dia anterior."

    def add_arguments(self, parser):
        parser.add_argument(
            "--data",
            type=date.fromisoformat,
            default=date.today() - timedelta(days=1),
            help="Data de referência no formato AAAA-MM-DD.",
        )

    def handle(self, *args, **options):
        try:
            brief = sync_daily_news(options["data"])
        except (requests.RequestException, ValueError) as error:
            raise CommandError(f"Não foi possível atualizar as notícias: {error}") from error
        self.stdout.write(
            self.style.SUCCESS(
                f"Feed do Poder360 atualizado com "
                f"{NewsArticle.objects.filter(source__identifier='poder360-rss').count()} notícias. "
                f"Resumo de {brief.reference_date:%d/%m/%Y}: {brief.article_count} itens."
            )
        )
