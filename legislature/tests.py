from datetime import timedelta
from unittest import mock

import requests
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from .models import (
    DailyBrief,
    DataSource,
    LegislativeLevel,
    NewsArticle,
    Parliamentarian,
    Party,
    ProcessingEvent,
    Project,
    Vote,
    Voting,
)


class PublicPagesTests(TestCase):
    def setUp(self):
        self.source = DataSource.objects.create(
            name="Câmara dos Deputados - Dados Abertos",
            url="https://dadosabertos.camara.leg.br/",
            identifier="camara-dados-abertos",
            last_synced_at=timezone.now(),
        )
        self.news_source = DataSource.objects.create(
            name="Poder360",
            url="https://www.poder360.com.br/",
            identifier="poder360-rss",
            last_synced_at=timezone.now(),
        )
        self.party = Party.objects.create(name="Partido Teste", acronym="PTX", external_id="99")
        self.deputy = Parliamentarian.objects.create(
            external_id="1",
            name="Deputada Teste",
            state="SP",
            level=LegislativeLevel.FEDERAL,
            party=self.party,
            source=self.source,
        )
        self.project = Project.objects.create(
            external_id="10",
            code="PL 10/2026",
            title="Cria uma política pública de teste.",
            description="Detalhamento completo da política pública de teste.",
            type_description="Projeto de Lei",
            keywords="política pública; teste",
            situation="Aguardando apreciação pelo Senado Federal",
            presented_at=timezone.localdate(),
            level=LegislativeLevel.FEDERAL,
            author=self.deputy,
            source=self.source,
        )
        ProcessingEvent.objects.create(
            project=self.project,
            occurred_at=timezone.now(),
            description="Apresentação",
            source=self.source,
        )
        self.voting = Voting.objects.create(
            external_id="10-1",
            project=self.project,
            title="Votação do projeto",
            description="O projeto trata de uma política pública de teste.",
            voted_at=timezone.now(),
            result="Aprovado",
            level=LegislativeLevel.FEDERAL,
            source=self.source,
            official_url="https://dadosabertos.camara.leg.br/",
        )
        Vote.objects.create(voting=self.voting, parliamentarian=self.deputy, choice=Vote.Choice.YES)
        yesterday = timezone.localdate() - timedelta(days=1)
        DailyBrief.objects.create(reference_date=yesterday, summary="Resumo de teste.", article_count=1)
        NewsArticle.objects.create(
            title="Notícia política de teste",
            url="https://example.com/noticia",
            summary="Resumo da notícia.",
            published_at=timezone.now() - timedelta(days=1),
            category=NewsArticle.Category.POLITICS,
            source=self.news_source,
        )

    def test_main_pages_render(self):
        for path in ("/", "/dashboard/", "/votacoes/", "/parlamentares/", "/entenda/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_lazy_detail_pages_render_saved_data(self):
        self.assertEqual(self.client.get(f"/projetos/{self.project.pk}/").status_code, 200)
        response = self.client.get(f"/votacoes/{self.voting.pk}/")
        self.assertContains(response, "Deputada Teste")
        self.assertContains(response, "Sim")
        self.assertContains(response, "Do que trata o projeto")
        self.assertContains(response, "Assuntos tratados")
        self.assertContains(response, self.project.keywords)
        self.assertNotContains(response, "Para que era esta votação?")

    def test_dashboard_shows_nominal_voting_indicators(self):
        response = self.client.get("/dashboard/")
        self.assertContains(response, "Votações nominais")
        self.assertContains(response, "Como cada partido votou")
        self.assertContains(response, "PTX")
        self.assertContains(response, str(timezone.localdate().year))

    def test_dashboard_api_includes_unfiltered_votes(self):
        response = self.client.get("/api/v1/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["votes"][Vote.Choice.YES], 1)

    def test_voting_list_shows_only_the_latest_ten_by_default(self):
        Project.objects.create(
            external_id="11",
            code="PL 11/2026",
            title="Projeto sem votação nominal",
            level=LegislativeLevel.FEDERAL,
            source=self.source,
        )
        response = self.client.get("/votacoes/")
        self.assertContains(response, "Últimas 10 votações nominais")
        self.assertContains(response, "Votações")
        self.assertContains(response, self.project.title)
        self.assertNotContains(response, "Projeto sem votação nominal")
        self.assertNotContains(response, "Todos os partidos")
        self.assertEqual(self.client.get("/projetos/").status_code, 302)

    def test_voting_list_fetches_camara_range_when_filtering(self):
        past = timezone.localdate() - timedelta(days=30)
        with mock.patch("legislature.views.import_nominal_votings_range", return_value=0) as fetch:
            response = self.client.get(f"/votacoes/?inicio={past - timedelta(days=5)}&fim={past}")
        fetch.assert_called_once()
        self.assertContains(response, "Nenhuma votação nominal encontrada")
        self.assertNotContains(response, self.project.title)
        response = self.client.get("/votacoes/?inicio=texto-invalido&fim=")
        self.assertContains(response, self.project.title)

    def test_party_and_state_filters_apply_to_voting_detail(self):
        response = self.client.get(f"/votacoes/{self.voting.pk}/?party=PTX&state=SP")
        self.assertContains(response, "Deputada Teste")

    def test_parliamentarian_page_lists_votes_and_presented_projects(self):
        with mock.patch("legislature.views.fetch_author_propositions", return_value=([self.project], 4)) as fetch:
            response = self.client.get(f"/parlamentares/{self.deputy.pk}/")
            self.assertContains(response, "Como votou desde 2023")
            self.assertContains(response, "Sim")
            self.assertContains(response, "Projetos apresentados em 2026")
            self.assertContains(response, self.project.code)
            self.assertContains(response, f"/projetos/{self.project.pk}/")
            self.assertContains(response, "Emendas")
            self.assertContains(response, "página 1 de 4")
            self.assertContains(response, "7 por página")
            self.assertNotContains(response, "Ver no portal da Câmara")
            self.assertNotContains(response, self.voting.description)
            self.assertNotContains(response, "{empty}")
            self.assertEqual(fetch.call_args.args[1], 2026)
            self.assertEqual(fetch.call_args.args[2], 1)
            self.assertEqual(fetch.call_args.kwargs["per_page"], 7)
            self.client.get(f"/parlamentares/{self.deputy.pk}/?tipo=PEC")
            self.assertEqual(fetch.call_args.kwargs["kind"], "PEC")

    def test_parliamentarian_list_hides_incomplete_records(self):
        Parliamentarian.objects.create(
            external_id="ghost",
            name="",
            state="",
            level=LegislativeLevel.FEDERAL,
            source=self.source,
            is_active=True,
        )
        response = self.client.get("/parlamentares/")
        self.assertContains(response, self.deputy.name)
        self.assertNotContains(response, "ghost")
        self.assertEqual(response.content.decode().count('class="row-link"'), 1)

    def test_project_detail_explains_the_proposal(self):
        response = self.client.get(f"/projetos/{self.project.pk}/")
        self.assertContains(response, "Do que se trata")
        self.assertContains(response, "política pública de teste")
        self.assertNotContains(response, "Abrir registro oficial")

    def test_summary_comes_from_attached_full_text(self):
        from services.teor import summarize_from_teor

        raw = (
            "PROJETO DE LEI\n"
            "Dispõe sobre a criação de uma política pública de teste no âmbito federal.\n"
            "O Congresso Nacional decreta:\n"
            "Art. 1º Fica instituída a política pública de teste para os municípios brasileiros.\n"
            "JUSTIFICAÇÃO\n"
            "A medida se justifica diante da ausência de regra nacional sobre o tema. "
            "O texto busca organizar o atendimento sem aumentar despesa obrigatória.\n"
        )
        summary = summarize_from_teor(raw, self.project)
        self.assertIn("\n\n", summary)
        self.assertIn("política pública de teste", summary.lower())
        self.assertIn("ausência de regra", summary.lower())

    def test_parliamentarian_page_survives_camara_outage(self):
        with mock.patch("legislature.views.fetch_author_propositions", side_effect=requests.ConnectionError("sem rede")):
            response = self.client.get(f"/parlamentares/{self.deputy.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Não foi possível consultar a Câmara agora")

    def test_guide_page_explains_election_and_proposition_types(self):
        response = self.client.get("/entenda/")
        self.assertContains(response, "Entenda")
        self.assertContains(response, "Como alguém vira deputado federal")
        self.assertContains(response, "quociente eleitoral")
        self.assertContains(response, "lista aberta")
        self.assertContains(response, "Projeto de Lei (PL)")
        self.assertContains(response, "Proposta de Emenda à Constituição (PEC)")
        self.assertContains(response, "Requerimentos")
        self.assertContains(response, "Decretos legislativos")
        self.assertContains(self.client.get("/"), "nav-link")
        home = self.client.get("/")
        self.assertContains(home, 'href="/entenda/"')

    def test_site_footer_appears_on_public_pages(self):
        response = self.client.get("/")
        self.assertContains(response, "site-footer")
        self.assertContains(response, "Fontes oficiais")
        self.assertContains(response, "Câmara dos Deputados")
        self.assertContains(response, "Poder360")
        self.assertContains(response, "Entrar")

    def test_login_page_authenticates_user(self):
        User.objects.create_user(username="analista", password="senha-segura")
        response = self.client.get("/entrar/")
        self.assertContains(response, "Entrar no Radar Legislativo")
        self.assertContains(response, "Usuário")
        self.assertContains(response, "Senha")
        response = self.client.post("/entrar/", {"username": "analista", "password": "errada"}, follow=True)
        self.assertContains(response, "Usuário")
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        response = self.client.post("/entrar/", {"username": "analista", "password": "senha-segura"})
        self.assertRedirects(response, "/")
