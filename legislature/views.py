from datetime import date, datetime, timedelta
from urllib.parse import urlencode

import requests
from django.core.paginator import Paginator
from django.db.models import Count, Max, Prefetch, Q
from django.db.models.functions import ExtractMonth, ExtractYear
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from services.camara import PROPOSITION_KINDS, ensure_voting_projects, fetch_author_propositions, hydrate_project, hydrate_voting, import_nominal_votings_range, source, sync_recent_legislative_data
from services.teor import ensure_text_summary
from services.news import news_refresh_due, sync_daily_news

from .models import DailyBrief, LegislativeLevel, NewsArticle, Parliamentarian, Project, Theme, Vote, Voting


def _ensure_recent_data():
    data_source = source()
    stale = not data_source.last_synced_at or data_source.last_synced_at < timezone.now() - timedelta(hours=12)
    if stale:
        sync_recent_legislative_data()


def home(request):
    reference_date = timezone.localdate() - timedelta(days=1)
    sync_error = ""
    try:
        _ensure_recent_data()
    except requests.RequestException as error:
        sync_error = f"Dados legislativos temporariamente indisponíveis: {error}"
    if news_refresh_due():
        try:
            sync_daily_news(reference_date)
        except (requests.RequestException, ValueError) as error:
            sync_error = sync_error or f"Notícias temporariamente indisponíveis: {error}"
    brief = DailyBrief.objects.filter(reference_date=reference_date).first()
    articles = NewsArticle.objects.filter(
        category=NewsArticle.Category.POLITICS,
        source__identifier="poder360-rss",
    ).select_related("source")[:12]
    context = {
        "reference_date": reference_date,
        "brief": brief,
        "articles": articles,
        "sync_error": sync_error,
        "projects": Project.objects.filter(votings__votes__isnull=False).annotate(latest_vote=Max("votings__voted_at")).select_related("author").order_by("-latest_vote")[:6],
        "votings": Voting.objects.filter(votes__isnull=False, project__isnull=False).distinct().select_related("project").order_by("-voted_at")[:6],
    }
    return render(request, "home.html", context)


MONTH_LABELS = ("Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez")


def dashboard(request):
    available_years = list(
        Voting.objects.filter(votes__isnull=False)
        .annotate(year=ExtractYear("voted_at"))
        .values_list("year", flat=True)
        .distinct()
        .order_by("-year")
    )
    try:
        selected_year = int(request.GET.get("year") or 0)
    except ValueError:
        selected_year = 0
    if selected_year not in available_years:
        selected_year = available_years[0] if available_years else date.today().year

    voting_ids = list(
        Voting.objects.filter(
            level=LegislativeLevel.FEDERAL,
            voted_at__year=selected_year,
            votes__isnull=False,
        )
        .values_list("id", flat=True)
        .distinct()
    )
    votings = Voting.objects.filter(id__in=voting_ids)
    votes = Vote.objects.filter(voting_id__in=voting_ids)
    choice_labels = dict(Vote.Choice.choices)

    total_votings = len(voting_ids)
    approved = votings.filter(result="Aprovado").count()
    rejected = votings.filter(result="Não aprovado").count()
    total_votes = votes.count()

    monthly_totals = dict(
        votings.annotate(month=ExtractMonth("voted_at"))
        .values_list("month")
        .annotate(total=Count("id"))
    )
    monthly_data = [
        {"label": label, "total": monthly_totals.get(index, 0)}
        for index, label in enumerate(MONTH_LABELS, start=1)
    ]

    vote_data = [
        {"label": choice_labels.get(row["choice"], row["choice"]), "total": row["total"]}
        for row in votes.values("choice").annotate(total=Count("id")).order_by("-total")
    ]

    party_totals = {}
    for row in (
        votes.exclude(parliamentarian__party__acronym="")
        .values("parliamentarian__party__acronym", "choice")
        .annotate(total=Count("id"))
    ):
        entry = party_totals.setdefault(
            row["parliamentarian__party__acronym"],
            {"party": row["parliamentarian__party__acronym"], "total": 0},
        )
        entry[row["choice"]] = row["total"]
        entry["total"] += row["total"]
    party_data = sorted(party_totals.values(), key=lambda item: item["total"], reverse=True)[:12]
    party_series = [
        {
            "choice": choice,
            "label": label,
            "values": [item.get(choice, 0) for item in party_data],
        }
        for choice, label in Vote.Choice.choices
    ]

    status_labels = dict(Project.Status.choices)
    status_data = [
        {"label": status_labels.get(row["status"], row["status"]), "total": row["total"]}
        for row in Project.objects.filter(votings__id__in=voting_ids)
        .values("status")
        .annotate(total=Count("id", distinct=True))
        .order_by("-total")
    ]

    context = {
        "selected_year": selected_year,
        "available_years": available_years,
        "total_votings": total_votings,
        "approved_count": approved,
        "rejected_count": rejected,
        "approval_rate": round(approved * 100 / total_votings, 1) if total_votings else 0,
        "projects_voted": Project.objects.filter(votings__id__in=voting_ids).distinct().count(),
        "deputies_voting": Parliamentarian.objects.filter(votes__voting_id__in=voting_ids).distinct().count(),
        "average_participation": round(total_votes / total_votings) if total_votings else 0,
        "monthly_data": monthly_data,
        "vote_data": vote_data,
        "party_labels": [item["party"] for item in party_data],
        "party_series": party_series,
        "status_data": status_data,
        "recent_votings": votings.select_related("project").order_by("-voted_at")[:6],
    }
    return render(request, "dashboard.html", context)


def parliamentarian_list(request):
    sync_error = ""
    try:
        _ensure_recent_data()
    except requests.RequestException as error:
        sync_error = str(error)
    queryset = (
        Parliamentarian.objects.filter(level=LegislativeLevel.FEDERAL, is_mock=False, is_active=True)
        .exclude(name="")
        .exclude(name__isnull=True)
        .select_related("party")
        .distinct()
    )
    if request.GET.get("q"):
        queryset = queryset.filter(Q(name__icontains=request.GET["q"]) | Q(civil_name__icontains=request.GET["q"]))
    page_obj = Paginator(queryset, 25).get_page(request.GET.get("page"))
    return render(request, "parliamentarian_list.html", {"page_obj": page_obj, "parliamentarians": page_obj.object_list, "sync_error": sync_error})


PRESENTED_YEAR = 2026


def parliamentarian_detail(request, pk):
    parliamentarian = get_object_or_404(Parliamentarian.objects.select_related("party"), pk=pk)
    votes = list(parliamentarian.votes.values("choice").annotate(total=Count("id")))
    choice_labels = dict(Vote.Choice.choices)
    for row in votes:
        row["label"] = choice_labels.get(row["choice"], row["choice"])
    vote_history = parliamentarian.votes.filter(voting__voted_at__date__gte=date(2023, 1, 1)).select_related("voting", "voting__project").order_by("-voting__voted_at")
    history_page = Paginator(vote_history, 5).get_page(request.GET.get("page"))
    expenses = parliamentarian.expenses.aggregate(total=__import__("django.db.models", fromlist=["Sum"]).Sum("value"))["total"] or 0
    try:
        presented_page = max(int(request.GET.get("apresentados") or 1), 1)
    except ValueError:
        presented_page = 1
    selected_kind = request.GET.get("tipo", "").strip().upper()
    if selected_kind not in PROPOSITION_KINDS:
        selected_kind = ""
    presented_projects = []
    presented_pages = 1
    presented_error = ""
    try:
        presented_projects, presented_pages = fetch_author_propositions(
            parliamentarian, PRESENTED_YEAR, presented_page, per_page=7, kind=selected_kind
        )
    except requests.RequestException as error:
        presented_error = str(error)
    presented_pages = max(int(presented_pages or 1), 1)
    return render(request, "parliamentarian_detail.html", {
        "parliamentarian": parliamentarian,
        "votes": votes,
        "history_page": history_page,
        "vote_history": history_page.object_list,
        "vote_total": sum(row["total"] for row in votes),
        "expenses_total": expenses,
        "presented_year": PRESENTED_YEAR,
        "presented_projects": presented_projects,
        "presented_page": presented_page,
        "presented_pages": presented_pages,
        "presented_error": presented_error,
        "kind_filters": [{"key": key, "label": value["label"]} for key, value in PROPOSITION_KINDS.items()],
        "selected_kind": selected_kind,
        "history_query": urlencode({"apresentados": presented_page, "tipo": selected_kind}),
        "presented_query": urlencode({"page": history_page.number, "tipo": selected_kind}),
    })


def _parse_date_param(value):
    value = (value or "").strip()
    if not value:
        return None
    parsed = parse_date(value)
    if parsed:
        return parsed
    try:
        return datetime.strptime(value, "%d/%m/%Y").date()
    except ValueError:
        return None


EARLIEST_VOTING_DATE = date(2023, 1, 1)


def _search_date_range(request):
    today = timezone.localdate()
    start_date = _parse_date_param(request.GET.get("inicio"))
    end_date = _parse_date_param(request.GET.get("fim"))
    if start_date or end_date:
        start_date = start_date or EARLIEST_VOTING_DATE
        end_date = end_date or today
        if start_date < EARLIEST_VOTING_DATE:
            start_date = EARLIEST_VOTING_DATE
        if end_date > today:
            end_date = today
        if start_date > end_date:
            start_date, end_date = end_date, start_date
    return start_date, end_date


def voting_list(request):
    sync_error = ""
    query = request.GET.get("q", "").strip()
    start_date, end_date = _search_date_range(request)
    searching = bool(query or start_date or end_date)
    votings = Voting.objects.filter(level=LegislativeLevel.FEDERAL).select_related("project")
    if searching:
        range_start = start_date or EARLIEST_VOTING_DATE
        range_end = end_date or timezone.localdate()
        if start_date or end_date:
            try:
                import_nominal_votings_range(range_start, range_end)
            except requests.RequestException as error:
                sync_error = str(error)
        votings = votings.filter(voted_at__date__gte=range_start, voted_at__date__lte=range_end)
        if query:
            votings = votings.filter(
                Q(project__title__icontains=query)
                | Q(project__code__icontains=query)
                | Q(title__icontains=query)
                | Q(description__icontains=query)
            )
        votings = votings.distinct().order_by("-voted_at")
        page_obj = Paginator(votings, 10).get_page(request.GET.get("page"))
        try:
            ensure_voting_projects(page_obj.object_list)
        except requests.RequestException as error:
            sync_error = sync_error or str(error)
    else:
        votings = votings.filter(votes__isnull=False, project__isnull=False).distinct().order_by("-voted_at")[:10]
        page_obj = None
    return render(request, "voting_list.html", {
        "page_obj": page_obj,
        "votings": page_obj.object_list if page_obj else votings,
        "searching": searching,
        "query": query,
        "start_date": start_date,
        "end_date": end_date,
        "filter_query": urlencode({
            "q": query,
            "inicio": start_date.isoformat() if start_date else "",
            "fim": end_date.isoformat() if end_date else "",
        }),
        "sync_error": sync_error,
    })


def project_detail(request, pk):
    project = get_object_or_404(Project.objects.select_related("author", "source"), pk=pk, level=LegislativeLevel.FEDERAL)
    sync_error = ""
    if not project.processing_events.exists() or not project.full_text_url or request.GET.get("atualizar"):
        try:
            project = hydrate_project(project)
        except requests.RequestException as error:
            sync_error = str(error)
    try:
        project = ensure_text_summary(project, force=bool(request.GET.get("atualizar")))
    except requests.RequestException as error:
        sync_error = sync_error or str(error)
    project = Project.objects.select_related("author", "source").prefetch_related(
        "themes",
        "committees",
        "processing_events",
        Prefetch(
            "votings",
            queryset=Voting.objects.filter(votes__isnull=False).distinct().prefetch_related("votes__parliamentarian"),
            to_attr="nominal_votings",
        ),
    ).get(pk=project.pk)
    return render(request, "project_detail.html", {
        "project": project,
        "sync_error": sync_error,
        "explanation": project.text_summary,
    })


def voting_detail(request, pk):
    voting = get_object_or_404(Voting.objects.select_related("project", "source"), pk=pk, level=LegislativeLevel.FEDERAL)
    sync_error = ""
    if not voting.votes.exists() or request.GET.get("atualizar"):
        try:
            voting = hydrate_voting(voting)
        except requests.RequestException as error:
            sync_error = str(error)
    voting = Voting.objects.select_related("project", "source").get(pk=voting.pk)
    all_votes = voting.votes.select_related("parliamentarian__party")
    party_choices = list(all_votes.exclude(parliamentarian__party__acronym="").values_list("parliamentarian__party__acronym", flat=True).distinct().order_by("parliamentarian__party__acronym"))
    state_choices = list(all_votes.exclude(parliamentarian__state="").values_list("parliamentarian__state", flat=True).distinct().order_by("parliamentarian__state"))
    selected_party = request.GET.get("party", "").strip()
    selected_state = request.GET.get("state", "").strip().upper()
    votes = all_votes
    if selected_party:
        votes = votes.filter(parliamentarian__party__acronym=selected_party)
    if selected_state:
        votes = votes.filter(parliamentarian__state=selected_state)
    vote_counts = list(votes.values("choice").annotate(total=Count("id")).order_by("choice"))
    choice_labels = dict(Vote.Choice.choices)
    for row in vote_counts:
        row["label"] = choice_labels.get(row["choice"], row["choice"])
    page_obj = Paginator(votes.order_by("parliamentarian__name"), 50).get_page(request.GET.get("page"))
    return render(request, "voting_detail.html", {
        "voting": voting,
        "page_obj": page_obj,
        "votes": page_obj.object_list,
        "vote_counts": vote_counts,
        "party_choices": party_choices,
        "state_choices": state_choices,
        "selected_party": selected_party,
        "selected_state": selected_state,
        "sync_error": sync_error,
    })


PROPOSITION_GUIDE = [
    {
        "anchor": "todos",
        "chip": "Todos",
        "title": "Todos",
        "plain": "Mostra tudo o que o deputado protocolou no ano, misturado.",
        "body": "Use este filtro quando quiser o retrato completo: projetos de lei, emendas, requerimentos e o restante na mesma lista. É o ponto de partida. Se a lista parecer bagunçada, escolha um tipo ao lado para ver só aquele grupo.",
    },
    {
        "anchor": "pl",
        "chip": "PL",
        "title": "Projeto de Lei (PL)",
        "plain": "É a proposta de uma lei comum, a que vale para o dia a dia do país.",
        "body": "O deputado apresenta um texto. Se a Câmara e o Senado aprovarem e o presidente sancionar, aquilo vira lei ordinária — por exemplo, regras de trânsito, saúde ou trabalho. Um PL sozinho não muda nada: só vale depois dessa tramitação. A maior parte do que a população chama de “projeto” é um PL.",
    },
    {
        "anchor": "pec",
        "chip": "PEC",
        "title": "Proposta de Emenda à Constituição (PEC)",
        "plain": "Não cria uma lei nova: tenta mudar a própria Constituição.",
        "body": "A Constituição é a regra mais alta do país. Uma PEC só passa com maioria qualificada (três quintos dos votos, em dois turnos, nas duas Casas). Por isso é mais difícil e mais grave do que um PL. Serve para temas estruturais: direitos, organização dos Poderes, regras eleitorais. Enquanto não for promulgada, a Constituição continua igual.",
    },
    {
        "anchor": "plp",
        "chip": "PLP",
        "title": "Projeto de Lei Complementar (PLP)",
        "plain": "É uma lei especial, pedida pela própria Constituição para detalhar um tema.",
        "body": "Alguns assuntos a Constituição não regula por inteiro: ela diz “isso será definido em lei complementar”. O PLP é esse detalhamento. Exige maioria absoluta (metade mais um de todos os deputados, não só dos presentes). Exemplos clássicos: normas gerais de direito tributário e regras de finanças públicas. É mais rígido que o PL e menos que a PEC.",
    },
    {
        "anchor": "emenda",
        "chip": "Emendas",
        "title": "Emendas",
        "plain": "Não abrem um projeto novo: alteram o texto de outra proposição que já está em discussão.",
        "body": "Quando um PL, uma PEC ou uma medida provisória já está na pauta, o deputado pode apresentar uma emenda para incluir, cortar ou reescrever um trecho. Sozinha, a emenda não vira lei. Ela só entra no texto final se for aprovada junto com a matéria principal. No Radar, este filtro junta emendas de comissão, de plenário e de relator.",
    },
    {
        "anchor": "requerimento",
        "chip": "Requerimentos",
        "title": "Requerimentos",
        "plain": "Não criam lei. Pedem uma providência da Câmara ou de um órgão do governo.",
        "body": "É o instrumento do expediente: pedir informação a um ministro (RIC), urgência para votar algo, criação de frente parlamentar, homenagem, convite para audiência. Aparece muito na ficha do deputado porque é o tipo mais usado no dia a dia. Um requerimento aprovado não muda a vida do cidadão como uma lei: resolve um trâmite interno ou cobra uma resposta.",
    },
    {
        "anchor": "decreto",
        "chip": "Decretos",
        "title": "Decretos legislativos (PDC e PDL)",
        "plain": "São decisões do Congresso que não passam pela sanção do presidente.",
        "body": "Servem para atos que a Constituição atribuiu às Casas: sustar um decreto do Executivo, aprovar um tratado, autorizar o presidente a se ausentar do país, escolher autoridades em alguns casos. O nome “decreto” aqui não é o decreto do presidente. É o Congresso decidindo por conta própria, sem precisar de sanção nem veto.",
    },
]


ELECTION_GUIDE = [
    {
        "title": "O cargo",
        "body": "O deputado federal representa o povo na Câmara dos Deputados, em Brasília. São 513 cadeiras no total. O mandato dura 4 anos e pode se reeleger sem limite de vezes. Não existe segundo turno para deputado: a eleição se resolve num único turno.",
    },
    {
        "title": "O voto é por Estado, não pelo Brasil inteiro",
        "body": "Você elege os deputados do seu Estado (ou do Distrito Federal). São Paulo elege o maior número de cadeiras; Roraima, o menor. A Constituição fixa o mínimo de 8 e o máximo de 70 vagas por unidade da Federação, conforme a população. Por isso o voto de um eleitor em Estado pequeno “pesa” mais na Câmara do que o de um eleitor paulista.",
    },
    {
        "title": "Quem pode se candidatar",
        "body": "Precisa ser brasileiro, ter 21 anos completos até a posse, estar em pleno exercício dos direitos políticos, ter domicílio eleitoral no Estado em que concorre e estar filiado a um partido há pelo menos 6 meses antes da eleição. Quem está inelegível (por exemplo, por condenação coberta pela Lei da Ficha Limpa) não pode concorrer. O registro da candidatura é feito no Tribunal Regional Eleitoral, sob as regras do TSE.",
    },
    {
        "title": "O partido (ou a federação) é obrigatório",
        "body": "Ninguém se elege deputado como avulso. A candidatura nasce numa lista partidária. Partidos podem se unir numa federação: na urna eles somam votos como se fossem um só e precisam permanecer juntos depois da eleição. A lei também exige que a lista tenha no mínimo 30% e no máximo 70% de candidaturas de cada sexo.",
    },
    {
        "title": "Como você vota",
        "body": "Na urna, o eleitor pode votar num candidato (digitando o número dele) ou só no partido (voto de legenda). Os dois tipos entram na conta do partido. Nulo e branco não elegem ninguém e não entram no quociente. O voto é facultativo aos 16 e 17 anos, obrigatório dos 18 aos 70 (exceto analfabetos) e de novo facultativo depois dos 70.",
    },
    {
        "title": "Primeiro o partido ganha a cadeira, depois o candidato",
        "body": "O sistema é proporcional de lista aberta. Soma-se tudo o que o partido (ou a federação) recebeu no Estado. Divide-se o total de votos válidos do Estado pelo número de vagas: esse é o quociente eleitoral. O partido leva tantas cadeiras quanto couber nessa divisão (quociente partidário). As vagas que sobram vão para quem tiver a melhor média. Só depois disso entram os nomes: dentro do partido que ganhou vagas, elegem-se os mais votados. Um candidato com muitos votos pode não se eleger se o partido não atingir o quociente; outro, com menos votos, pode se eleger se o partido fez uma boa soma.",
    },
    {
        "title": "Suplente",
        "body": "Quem ficou na sequência da lista do mesmo partido, por número de votos, vira suplente. Se o deputado assume ministério, se licenciar ou perder o mandato, o suplente ocupa a cadeira. Não há eleição extra no meio do mandato para repor um deputado federal.",
    },
    {
        "title": "Cláusula de desempenho do partido",
        "body": "Além de eleger gente, o partido precisa de um desempenho nacional mínimo para ter direito a fundo partidário cheio, tempo de TV e algumas prerrogativas na Câmara. A regra atual pede cerca de 2% dos votos válidos para a Câmara, espalhados em pelo menos um terço dos Estados, ou então 11 deputados em 9 Estados. Isso não impede um nome isolado de se eleger, mas define se o partido entra no jogo institucional com estrutura.",
    },
]


def guide(request):
    return render(request, "guide.html", {"items": PROPOSITION_GUIDE, "election": ELECTION_GUIDE})


def search(request):
    term = request.GET.get("q", "").strip()
    context = {"term": term, "parliamentarians": [], "projects": [], "themes": []}
    if term:
        context["parliamentarians"] = Parliamentarian.objects.filter(Q(name__icontains=term) | Q(civil_name__icontains=term)).exclude(name="")[:20]
        context["projects"] = Project.objects.filter(Q(title__icontains=term) | Q(code__icontains=term), votings__votes__isnull=False).distinct()[:20]
        context["themes"] = Theme.objects.filter(name__icontains=term)[:20]
    return render(request, "search.html", context)
