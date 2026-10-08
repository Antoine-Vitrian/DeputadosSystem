from datetime import date, timedelta
from unittest import mock

import requests
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from .models import (
    DailyBrief,
    DataSource,
    LegislativeLevel,
    Mandate,
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
        self.ranking_score_patcher = mock.patch(
            "legislature.views.fetch_parliamentarian_score", return_value=None
        )
        self.ranking_score_mock = self.ranking_score_patcher.start()
        self.addCleanup(self.ranking_score_patcher.stop)
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

    def test_voting_list_refreshes_recent_data_automatically(self):
        self.source.last_synced_at = timezone.now() - timedelta(hours=2)
        self.source.save(update_fields=["last_synced_at"])
        with mock.patch("legislature.views.sync_recent_legislative_data") as refresh:
            response = self.client.get("/votacoes/")
        self.assertEqual(response.status_code, 200)
        refresh.assert_called_once_with()

    def test_voting_list_fetches_camara_range_when_filtering(self):
        past = timezone.localdate() - timedelta(days=30)
        with mock.patch("legislature.views.import_nominal_votings_range", return_value=0) as fetch:
            response = self.client.get(f"/votacoes/?inicio={past - timedelta(days=5)}&fim={past}")
        fetch.assert_called_once()
        self.assertContains(response, "Nenhuma votação nominal encontrada")
        self.assertNotContains(response, self.project.title)
        response = self.client.get("/votacoes/?inicio=texto-invalido&fim=")
        self.assertContains(response, self.project.title)

    def test_voting_list_searches_the_archive_from_2010(self):
        with mock.patch("legislature.views.import_nominal_votings_range", return_value=0) as fetch:
            response = self.client.get("/votacoes/?inicio=2010-01-01&fim=2010-01-31")
        self.assertEqual(response.status_code, 200)
        fetch.assert_called_once_with(date(2010, 1, 1), date(2010, 1, 31))

    def test_voting_list_does_not_search_before_2010(self):
        with mock.patch("legislature.views.import_nominal_votings_range", return_value=0) as fetch:
            self.client.get("/votacoes/?inicio=2009-01-01&fim=2009-12-31")
        fetch.assert_called_once_with(date(2010, 1, 1), date(2010, 1, 1))

    def test_party_and_state_filters_apply_to_voting_detail(self):
        response = self.client.get(f"/votacoes/{self.voting.pk}/?party=PTX&state=SP")
        self.assertContains(response, "Deputada Teste")

    def test_parliamentarian_page_lists_votes_and_presented_projects(self):
        with mock.patch("legislature.views.fetch_author_propositions", return_value=([self.project], 4)) as fetch:
            response = self.client.get(f"/parlamentares/{self.deputy.pk}/")
            self.assertContains(response, "Como votou desde 2010")
            self.assertContains(response, "Sim")
            self.assertContains(response, "Proposições apresentadas")
            self.assertContains(response, "todo o histórico")
            self.assertContains(response, self.project.code)
            self.assertContains(response, f"/projetos/{self.project.pk}/")
            self.assertContains(response, "Emendas")
            self.assertContains(response, "página 1 de 4")
            self.assertContains(response, "7 por página")
            self.assertNotContains(response, "Ver no portal da Câmara")
            self.assertNotContains(response, self.voting.description)
            self.assertNotContains(response, "{empty}")
            self.assertIsNone(fetch.call_args.args[1])
            self.assertEqual(fetch.call_args.args[2], 1)
            self.assertEqual(fetch.call_args.kwargs["per_page"], 7)
            self.client.get(f"/parlamentares/{self.deputy.pk}/?tipo=PEC")
            self.assertEqual(fetch.call_args.kwargs["kind"], "PEC")
            self.client.get(f"/parlamentares/{self.deputy.pk}/?tipo=REQ&ano=2024&mes=3")
            self.assertEqual(fetch.call_args.args[1], 2024)
            self.assertEqual(fetch.call_args.kwargs["kind"], "REQ")
            self.assertEqual(fetch.call_args.kwargs["month"], 3)

    def test_parliamentarian_type_filters_render_as_chips(self):
        with mock.patch("legislature.views.fetch_author_propositions", return_value=([], 1)):
            response = self.client.get(f"/parlamentares/{self.deputy.pk}/")
        self.assertContains(response, 'class="kind-filters"')
        self.assertContains(response, 'type="radio" name="tipo"')
        self.assertNotContains(response, 'id="proposition-type"')
        self.assertContains(response, "input.form.requestSubmit()")
        self.assertContains(response, 'class="proposition-date-filters"')

    def test_parliamentarian_profile_displays_ranking_score(self):
        self.ranking_score_mock.return_value = {
            "score": 9.1,
            "url": "https://ranking.org.br/perfil/deputada-teste",
        }
        with mock.patch("legislature.views.fetch_author_propositions", return_value=([], 1)):
            response = self.client.get(f"/parlamentares/{self.deputy.pk}/")
        self.assertEqual(response.context["ranking_score"]["score"], 9.1)
        self.assertContains(response, "Nota acumulada")
        self.assertContains(response, "9,10")
        self.assertContains(response, "ranking-score-good")
        self.assertContains(response, "Boa")
        self.assertContains(response, "https://ranking.org.br/perfil/deputada-teste")

    def test_ranking_score_color_changes_by_score_band(self):
        with mock.patch("legislature.views.fetch_author_propositions", return_value=([], 1)):
            for score, css_class, label in (
                (8.0, "good", "Boa"),
                (6.0, "medium", "Mediana"),
                (4.0, "low", "Baixa"),
            ):
                with self.subTest(score=score):
                    self.ranking_score_mock.return_value = {
                        "score": score,
                        "url": "https://ranking.org.br/perfil/deputada-teste",
                    }
                    response = self.client.get(f"/parlamentares/{self.deputy.pk}/")
                    self.assertEqual(
                        response.context["ranking_rating"]["class"], css_class
                    )
                    self.assertContains(response, f"ranking-score-{css_class}")
                    self.assertContains(response, label)

    def test_parliamentarian_profile_survives_ranking_service_failure(self):
        self.ranking_score_mock.side_effect = requests.ConnectionError("Ranking indisponível")
        with mock.patch("legislature.views.fetch_author_propositions", return_value=([], 1)):
            response = self.client.get(f"/parlamentares/{self.deputy.pk}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Não foi possível consultar a pontuação agora")
        self.ranking_score_mock.side_effect = None
        self.ranking_score_mock.return_value = None

    def test_ranking_score_service_checks_identity_and_parses_score_and_details(self):
        from services.ranking import fetch_parliamentarian_score

        cache.clear()
        self.deputy.civil_name = "Adriana Miguel Ventura"
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "items": [{
                "nome": "Adriana Ventura",
                "nome_eleitoral": "Adriana Ventura",
                "nome_civil": "ADRIANA MIGUEL VENTURA",
                "slug": "adriana-miguel-ventura",
                "partido": "Partido Novo",
                "uf": "SÃO PAULO",
                "composicao_pontuacao": {"pontuacao": 9.1},
            }]
        }
        with mock.patch("services.ranking.requests.get", return_value=response) as get:
            result = fetch_parliamentarian_score(self.deputy)
        self.assertEqual(result["score"], 9.1)
        self.assertEqual(result["party"], "Partido Novo")
        self.assertEqual(result["state"], "SÃO PAULO")
        self.assertEqual(
            result["url"], "https://ranking.org.br/perfil/adriana-miguel-ventura"
        )
        self.assertIn("/api/filter-items-ranking?", get.call_args.args[0])
        self.assertIn("busca=Adriana", get.call_args.args[0])

    def test_ranking_score_service_rejects_mismatched_profile(self):
        from services.ranking import fetch_parliamentarian_score

        cache.clear()
        self.deputy.civil_name = "Nome do Deputado"
        response = mock.Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "items": [{
                "nome": "Outro Deputado",
                "nome_eleitoral": "Outro Deputado",
                "nome_civil": "OUTRO DEPUTADO",
                "slug": "outro-deputado",
                "composicao_pontuacao": {"pontuacao": 9.9},
            }]
        }
        with mock.patch("services.ranking.requests.get", return_value=response) as get:
            self.assertIsNone(fetch_parliamentarian_score(self.deputy))
        get.assert_called()

    def test_profile_uses_ranking_data_when_party_and_state_are_missing(self):
        self.deputy.party = None
        self.deputy.state = ""
        self.deputy.save(update_fields=["party", "state"])
        self.ranking_score_mock.return_value = {
            "score": 8.2,
            "url": "https://ranking.org.br/perfil/deputada-teste",
            "party": "Partido Teste",
            "state": "SÃO PAULO",
        }
        with (
            mock.patch("legislature.views.refresh_parliamentarian_identity", return_value=self.deputy),
            mock.patch("legislature.views.fetch_author_propositions", return_value=([], 1)),
        ):
            response = self.client.get(f"/parlamentares/{self.deputy.pk}/")
        self.assertEqual(response.context["party_display"], "Partido Teste")
        self.assertEqual(response.context["state_display"], "SÃO PAULO")
        self.assertContains(response, "Partido Teste")
        self.assertContains(response, "SÃO PAULO")

    def test_parliamentarian_sync_preserves_party_and_state_when_api_omits_them(self):
        from services.camara import upsert_parliamentarian

        upsert_parliamentarian(
            {"id": self.deputy.external_id, "nome": self.deputy.name},
            self.source,
        )
        self.deputy.refresh_from_db()
        self.assertEqual(self.deputy.party, self.party)
        self.assertEqual(self.deputy.state, "SP")

    def test_missing_party_and_state_are_refreshed_from_chamber_api(self):
        from services.camara import refresh_parliamentarian_identity

        self.deputy.party = None
        self.deputy.state = ""
        self.deputy.save(update_fields=["party", "state"])
        api = mock.Mock()
        api.get.return_value = {"dados": {
            "id": self.deputy.external_id,
            "nome": self.deputy.name,
            "siglaUf": "RJ",
            "siglaPartido": "PTX",
            "idPartido": 99,
        }}
        refreshed = refresh_parliamentarian_identity(self.deputy, api=api)
        self.assertEqual(refreshed.state, "RJ")
        self.assertEqual(refreshed.party.acronym, "PTX")

    def test_parliamentarian_sync_does_not_erase_existing_photo(self):
        from services.camara import upsert_parliamentarian

        self.deputy.photo_url = "https://example.com/deputy.jpg"
        self.deputy.save(update_fields=["photo_url"])
        upsert_parliamentarian(
            {"id": self.deputy.external_id, "nome": self.deputy.name},
            self.source,
        )
        self.deputy.refresh_from_db()
        self.assertEqual(self.deputy.photo_url, "https://example.com/deputy.jpg")

        upsert_parliamentarian(
            {
                "id": self.deputy.external_id,
                "nome": self.deputy.name,
                "urlFoto": "https://example.com/new-deputy.jpg",
            },
            self.source,
        )
        self.deputy.refresh_from_db()
        self.assertEqual(self.deputy.photo_url, "https://example.com/new-deputy.jpg")

    def test_parliamentarian_year_filter_waits_for_explicit_submit(self):
        response = self.client.get("/parlamentares/")
        self.assertNotContains(response, 'onchange="this.form.submit()"')

    def test_author_proposition_filters_reach_camara_api(self):
        from services.camara import fetch_author_propositions

        api = mock.Mock()
        api.all.return_value = []
        fetch_author_propositions(
            self.deputy, year=2024, month=3, kind="REQ", api=api
        )
        query = api.all.call_args.args[1]
        self.assertEqual(query["ano"], 2024)
        self.assertEqual(query["siglaTipo"], ["REQ", "RIC", "RCP"])
        self.assertEqual(query["ordenarPor"], "id")
        self.assertEqual(query["ordem"], "DESC")

    def test_author_proposition_history_can_query_all_years(self):
        from services.camara import fetch_author_propositions

        api = mock.Mock()
        api.all.return_value = []
        fetch_author_propositions(self.deputy, api=api)
        self.assertNotIn("ano", api.all.call_args.args[1])
        self.assertEqual(api.all.call_args.args[1]["ordenarPor"], "id")

    def test_author_propositions_are_sorted_by_date_and_filtered_by_month(self):
        from services.camara import fetch_author_propositions

        api = mock.Mock()
        api.all.return_value = [
            {
                "id": 300,
                "siglaTipo": "PL",
                "numero": 1,
                "ano": 2024,
                "dataApresentacao": "2024-03-02T10:00",
                "ementa": "Proposição mais nova",
            },
            {
                "id": 500,
                "siglaTipo": "PL",
                "numero": 2,
                "ano": 2024,
                "dataApresentacao": "2024-03-01T10:00",
                "ementa": "Proposição antiga com ID maior",
            },
            {
                "id": 400,
                "siglaTipo": "PL",
                "numero": 3,
                "ano": 2024,
                "dataApresentacao": "2024-02-28T10:00",
                "ementa": "Outro mês",
            },
        ]
        projects, pages = fetch_author_propositions(
            self.deputy, year=2024, month=3, per_page=1, api=api
        )
        self.assertEqual([project.title for project in projects], ["Proposição mais nova"])
        self.assertEqual(pages, 2)

    def test_parliamentarian_profile_does_not_show_expenses(self):
        with mock.patch("legislature.views.fetch_author_propositions", return_value=([], 1)):
            response = self.client.get(f"/parlamentares/{self.deputy.pk}/")
        self.assertNotContains(response, "Despesas registradas")
        self.assertNotContains(response, "expenses_total")
        self.assertNotContains(response, 'id="votes"')
        self.assertContains(response, "1 votos nominais registrados")

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

    def test_parliamentarian_list_filters_by_name_party_and_state(self):
        other_party = Party.objects.create(name="Outro Partido", acronym="OUT", external_id="100")
        Parliamentarian.objects.create(
            external_id="2",
            name="Deputado Outro Estado",
            state="RJ",
            level=LegislativeLevel.FEDERAL,
            party=self.party,
            source=self.source,
        )
        Parliamentarian.objects.create(
            external_id="3",
            name="Deputado Outro Partido",
            state="SP",
            level=LegislativeLevel.FEDERAL,
            party=other_party,
            source=self.source,
        )

        response = self.client.get(
            "/parlamentares/",
            {"q": "Teste", "partido": self.party.pk, "estado": "SP"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.deputy.name)
        self.assertNotContains(response, "Deputado Outro Estado")
        self.assertNotContains(response, "Deputado Outro Partido")
        self.assertContains(response, 'name="partido"')
        self.assertContains(response, 'name="estado"')
        self.assertEqual(response.context["selected_party"], str(self.party.pk))
        self.assertEqual(response.context["selected_state"], "SP")

    def test_parliamentarian_list_can_select_a_historical_year(self):
        self.deputy.is_active = False
        self.deputy.save(update_fields=["is_active"])
        historical = Parliamentarian.objects.create(
            external_id="historical",
            name="Deputado de outra legislatura",
            level=LegislativeLevel.FEDERAL,
            source=self.source,
            is_active=False,
        )

        def sync_year(year):
            self.assertEqual(year, 2010)
            Mandate.objects.create(
                parliamentarian=historical,
                start_date=date(2007, 2, 1),
                end_date=date(2011, 1, 31),
                description="Legislatura 2007-2011",
            )

        with mock.patch("legislature.views.sync_deputies_for_year", side_effect=sync_year) as sync:
            response = self.client.get("/parlamentares/?ano=2010")
        self.assertEqual(response.status_code, 200)
        sync.assert_called_once_with(2010)
        self.assertContains(response, historical.name)
        self.assertNotContains(response, self.deputy.name)
        self.assertContains(response, "Deputados em 2010")

    def test_historical_deputy_sync_imports_and_caches_mandates(self):
        from services.camara import sync_deputies_for_year

        api = mock.Mock()
        api.all.side_effect = [
            [{
                "id": 53,
                "dataInicio": "2007-02-01",
                "dataFim": "2011-01-31",
            }],
            [{
                "id": 22,
                "nome": "Deputado Histórico",
                "siglaUf": "SP",
            }],
        ]
        with mock.patch("services.camara.source", return_value=self.source):
            self.assertEqual(sync_deputies_for_year(2010, api=api), 1)

        historical = Parliamentarian.objects.get(external_id="22")
        mandate = Mandate.objects.get(parliamentarian=historical)
        self.assertEqual(mandate.start_date, date(2007, 2, 1))
        self.assertEqual(mandate.end_date, date(2011, 1, 31))

        unused_api = mock.Mock()
        with mock.patch("services.camara.source", return_value=self.source):
            self.assertEqual(sync_deputies_for_year(2010, api=unused_api), 1)
        unused_api.all.assert_not_called()

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
