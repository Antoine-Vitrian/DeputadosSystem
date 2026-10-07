from datetime import date, datetime, timedelta
from decimal import Decimal
from calendar import monthrange
from math import ceil
import re
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from legislature.models import DataSource, Expense, LegislativeLevel, Mandate, Notification, Parliamentarian, Party, ProcessingEvent, Project, Vote, Voting

BASE_URL = "https://dadosabertos.camara.leg.br/api/v2/"


class CamaraAPI:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json", "User-Agent": "RadarLegislativo/1.0"})
        retry = Retry(total=3, backoff_factor=0.4, status_forcelist=(429, 500, 502, 503, 504))
        self.session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10))

    def get(self, path, params=None):
        response = self.session.get(urljoin(BASE_URL, path), params=params, timeout=(5, 30))
        response.raise_for_status()
        return response.json()

    def all(self, path, params=None, max_pages=None):
        params = dict(params or {})
        params.setdefault("itens", 100)
        items = []
        page = 1
        while True:
            params["pagina"] = page
            payload = self.get(path, params)
            items.extend(payload.get("dados", []))
            next_link = next((link.get("href") for link in payload.get("links", []) if link.get("rel") == "next"), None)
            if not next_link or (max_pages and page >= max_pages):
                return items
            page += 1


def source():
    return DataSource.objects.get_or_create(name="Câmara dos Deputados - Dados Abertos", defaults={"url": "https://dadosabertos.camara.leg.br/", "identifier": "camara-dados-abertos"})[0]


def upsert_party(data):
    acronym = data.get("siglaPartido") or ""
    if not acronym:
        return None
    external_id = data.get("idPartido")
    if not external_id and data.get("uriPartido"):
        external_id = data["uriPartido"].rstrip("/").rsplit("/", 1)[-1]
    if external_id:
        party = Party.objects.filter(external_id=str(external_id)).first()
        if party:
            changed = []
            if party.acronym != acronym:
                party.acronym = acronym
                changed.append("acronym")
            if party.name != acronym:
                party.name = acronym
                changed.append("name")
            if changed:
                party.save(update_fields=changed)
            return party
    party = Party.objects.filter(acronym=acronym).first()
    if party:
        if external_id and not party.external_id:
            party.external_id = str(external_id)
            party.save(update_fields=["external_id"])
        return party
    return Party.objects.create(name=acronym, acronym=acronym, external_id=str(external_id) if external_id else None)


def upsert_parliamentarian(data, data_source, mark_active=False):
    name = (data.get("nome") or "").strip()
    party = upsert_party(data)
    defaults = {"civil_name": data.get("nomeCivil", ""), "photo_url": data.get("urlFoto", ""), "role": "Deputado federal", "state": data.get("siglaUf", ""), "level": LegislativeLevel.FEDERAL, "party": party, "source": data_source, "is_mock": False}
    parliamentarian = Parliamentarian.objects.filter(external_id=str(data["id"])).first()
    if parliamentarian:
        if name:
            defaults["name"] = name
        if mark_active and (name or parliamentarian.name):
            defaults["is_active"] = True
        for field, value in defaults.items():
            setattr(parliamentarian, field, value)
        parliamentarian.save()
        return parliamentarian
    return Parliamentarian.objects.create(external_id=str(data["id"]), name=name, is_active=bool(mark_active and name), **defaults)


def parse_year(value):
    parsed = parse_datetime(value) if value and "T" in value else parse_date(value) if value else None
    return parsed.year if parsed else None


SITUATION_STATUS = (
    ("transformad", Project.Status.APPROVED),
    ("aprovad", Project.Status.APPROVED),
    ("rejeitad", Project.Status.REJECTED),
    ("arquivad", Project.Status.ARCHIVED),
    ("retirad", Project.Status.ARCHIVED),
)


def _status_from_situation(situation):
    text = (situation or "").lower()
    return next((status for needle, status in SITUATION_STATUS if needle in text), None)


def upsert_project(data, data_source, author=None):
    defaults = {"level": LegislativeLevel.FEDERAL, "source": data_source, "is_mock": False}
    if data.get("siglaTipo"):
        defaults["code"] = f"{data['siglaTipo']} {data.get('numero', data['id'])}/{data.get('ano', '')}"
        defaults.setdefault("type_description", data["siglaTipo"][:120])
    if data.get("ementa"):
        defaults["title"] = data["ementa"]
    if data.get("ementaDetalhada"):
        defaults["description"] = data["ementaDetalhada"]
    if data.get("descricaoTipo"):
        defaults["type_description"] = data["descricaoTipo"][:120]
    if data.get("keywords"):
        defaults["keywords"] = data["keywords"]
    if data.get("urlInteiroTeor"):
        defaults["full_text_url"] = data["urlInteiroTeor"]
    raw_date = data.get("dataApresentacao") or (data.get("statusProposicao") or {}).get("dataHora") or ""
    presented_at = parse_date(str(raw_date)[:10]) if raw_date else None
    if presented_at:
        defaults["presented_at"] = presented_at
    if author is not None:
        defaults["author"] = author
    status_info = data.get("statusProposicao") or {}
    if status_info.get("descricaoSituacao"):
        defaults["situation"] = status_info["descricaoSituacao"][:240]
        mapped_status = _status_from_situation(status_info["descricaoSituacao"])
        if mapped_status:
            defaults["status"] = mapped_status
    if status_info.get("regime"):
        defaults["regime"] = status_info["regime"][:160]
    defaults.setdefault("title", "Sem ementa")
    defaults.setdefault("code", f"PROP {data['id']}")
    project, created = Project.objects.update_or_create(external_id=str(data["id"]), defaults=defaults)
    if created:
        Notification.objects.create(project=project, message=f"Novo projeto sincronizado: {project.code}")
    return project


@transaction.atomic
def sync_deputies(api, data_source, start_year, end_year):
    items = api.all("deputados", {"ordem": "ASC", "ordenarPor": "nome"})
    Parliamentarian.objects.filter(level=LegislativeLevel.FEDERAL, is_mock=False).update(is_active=False)
    for item in items:
        parliamentarian = upsert_parliamentarian(item, data_source, mark_active=True)
        Mandate.objects.get_or_create(
            parliamentarian=parliamentarian,
            start_date=f"{date.today().year}-01-01",
            defaults={"description": "Mandato federal atual"},
        )
    data_source.last_synced_at = timezone.now()
    data_source.save(update_fields=["last_synced_at"])
    return len(items)


def sync_projects(api, data_source, start_year, end_year, max_pages=None):
    total = 0
    for year in range(start_year, end_year + 1):
        params = {"ano": year, "ordem": "DESC", "ordenarPor": "id"}
        for item in api.all("proposicoes", params, max_pages=max_pages):
            detail = api.get(f"proposicoes/{item['id']}").get("dados", {})
            author = None
            for author_data in api.get(f"proposicoes/{item['id']}/autores").get("dados", []):
                uri = author_data.get("uri", "")
                if "/deputados/" not in uri:
                    continue
                deputy_id = uri.rstrip("/").rsplit("/", 1)[-1]
                deputy_data = api.get(f"deputados/{deputy_id}").get("dados", {})
                if deputy_data:
                    author = upsert_parliamentarian(deputy_data, data_source)
                break
            upsert_project({**item, **detail}, data_source, author)
            total += 1
    return total


def sync_votings(api, data_source, start_year, end_year, max_pages=None):
    total = 0
    for year in range(start_year, end_year + 1):
        for quarter_start, quarter_end in ((1, 3), (4, 6), (7, 9), (10, 12)):
            end_day = 31 if quarter_end in (3, 12) else 30
            start = f"{year}-{quarter_start:02d}-01"
            end = f"{year}-{quarter_end:02d}-{end_day:02d}"
            votings = api.all("votacoes", {"dataInicio": start, "dataFim": end}, max_pages=max_pages)
            for item in votings:
                detail = api.get(f"votacoes/{item['id']}").get("dados", {})
                affected = detail.get("proposicoesAfetadas") or []
                project = upsert_project(affected[0], data_source) if affected else None
                voted_at = parse_datetime(item.get("dataHoraRegistro")) or parse_datetime(f"{item['data']}T00:00:00")
                voting, created = Voting.objects.update_or_create(
                    external_id=str(item["id"]),
                    defaults={
                        "project": project,
                        "title": detail.get("descricao", item.get("descricao", "Votação plenária"))[:300],
                        "voted_at": timezone.make_aware(voted_at) if voted_at and timezone.is_naive(voted_at) else voted_at,
                        "result": detail.get("descricao", item.get("descricao", ""))[:120],
                        "level": LegislativeLevel.FEDERAL,
                        "source": data_source,
                        "official_url": item.get("uri", ""),
                    },
                )
                if created:
                    Notification.objects.create(voting=voting, message=f"Nova votação sincronizada: {voting.title[:220]}")
                hydrate_voting(voting, api)
                total += 1
    return total


def sync_recent_legislative_data(days=120, page_count=5, nominal_target=12):
    api = CamaraAPI()
    data_source = source()
    sync_deputies(api, data_source, date.today().year, date.today().year)
    start = timezone.localdate() - timedelta(days=days)
    nominal_found = 0
    scanned = 0
    for page in range(1, page_count + 1):
        payload = api.get(
            "votacoes",
            {
                "dataInicio": start.isoformat(),
                "dataFim": timezone.localdate().isoformat(),
                "ordem": "DESC",
                "ordenarPor": "dataHoraRegistro",
                "itens": 100,
                "pagina": page,
            },
        )
        items = payload.get("dados", [])
        if not items:
            break
        for item in items:
            scanned += 1
            description = item.get("descricao", "")
            if not re.search(r"\bSim:\s*\d+.*\bN(?:ã|a)o:\s*\d+", description, re.IGNORECASE):
                continue
            voted_at = parse_datetime(item.get("dataHoraRegistro")) or parse_datetime(f"{item['data']}T00:00:00")
            voting, _ = Voting.objects.update_or_create(
                external_id=str(item["id"]),
                defaults={
                    "title": description[:300],
                    "voted_at": timezone.make_aware(voted_at) if voted_at and timezone.is_naive(voted_at) else voted_at,
                    "result": description[:120],
                    "level": LegislativeLevel.FEDERAL,
                    "source": data_source,
                    "official_url": item.get("uri", ""),
                },
            )
            hydrate_voting(voting, api)
            if voting.project_id and voting.votes.exists():
                nominal_found += 1
            if nominal_found >= nominal_target:
                break
        if nominal_found >= nominal_target:
            break
    return {
        "deputies": Parliamentarian.objects.filter(level=LegislativeLevel.FEDERAL, is_active=True, is_mock=False).count(),
        "projects": Project.objects.filter(votings__votes__isnull=False, is_mock=False).distinct().count(),
        "votings": nominal_found,
        "scanned": scanned,
    }


def sync_nominal_votings_year(year, max_pages=None):
    api = CamaraAPI()
    data_source = source()
    end_date = min(timezone.localdate(), date(year, 12, 31))
    pages = 0
    scanned = 0
    nominal = 0
    for month in range(1, end_date.month + 1):
        period_start = date(year, month, 1)
        period_end = min(date(year, month, monthrange(year, month)[1]), end_date)
        page = 1
        while not max_pages or page <= max_pages:
            payload = api.get(
                "votacoes",
                {
                    "dataInicio": period_start.isoformat(),
                    "dataFim": period_end.isoformat(),
                    "ordem": "DESC",
                    "ordenarPor": "dataHoraRegistro",
                    "itens": 100,
                    "pagina": page,
                },
            )
            pages += 1
            items = payload.get("dados", [])
            if not items:
                break
            for item in items:
                scanned += 1
                description = item.get("descricao", "")
                if not (
                    re.search(r"\bSim:\s*\d+", description, re.IGNORECASE)
                    and re.search(r"\bN(?:ã|a)o:\s*\d+", description, re.IGNORECASE)
                ):
                    continue
                voted_at = parse_datetime(item.get("dataHoraRegistro")) or parse_datetime(f"{item['data']}T00:00:00")
                voting, _ = Voting.objects.update_or_create(
                    external_id=str(item["id"]),
                    defaults={
                        "title": description[:300],
                        "voted_at": timezone.make_aware(voted_at) if voted_at and timezone.is_naive(voted_at) else voted_at,
                        "result": description[:120],
                        "level": LegislativeLevel.FEDERAL,
                        "source": data_source,
                        "official_url": item.get("uri", ""),
                    },
                )
                hydrate_voting(voting, api)
                if voting.project_id and voting.votes.exists():
                    nominal += 1
            has_next = any(link.get("rel") == "next" for link in payload.get("links", []))
            if not has_next:
                break
            page += 1
    data_source.last_synced_at = timezone.now()
    data_source.save(update_fields=["last_synced_at"])
    return {
        "year": year,
        "pages": pages,
        "scanned": scanned,
        "votings": nominal,
        "projects": Project.objects.filter(
            votings__voted_at__year=year,
            votings__votes__isnull=False,
            is_mock=False,
        ).distinct().count(),
    }


def _iter_months(start_date, end_date):
    cursor = date(start_date.year, start_date.month, 1)
    last = date(end_date.year, end_date.month, 1)
    while cursor <= last:
        month_end = date(cursor.year, cursor.month, monthrange(cursor.year, cursor.month)[1])
        yield max(cursor, start_date), min(month_end, end_date)
        cursor = date(cursor.year + 1, 1, 1) if cursor.month == 12 else date(cursor.year, cursor.month + 1, 1)


def _is_nominal_description(description):
    return bool(
        re.search(r"\bSim:\s*\d+", description or "", re.IGNORECASE)
        and re.search(r"\bN(?:ã|a)o:\s*\d+", description or "", re.IGNORECASE)
    )


def import_nominal_votings_range(start_date, end_date, api=None):
    """Importa só a lista de votações nominais do intervalo, sem baixar cada voto."""
    api = api or CamaraAPI()
    data_source = source()
    imported = 0
    for period_start, period_end in _iter_months(start_date, end_date):
        page = 1
        while True:
            payload = api.get(
                "votacoes",
                {
                    "dataInicio": period_start.isoformat(),
                    "dataFim": period_end.isoformat(),
                    "ordem": "DESC",
                    "ordenarPor": "dataHoraRegistro",
                    "itens": 100,
                    "pagina": page,
                },
            )
            items = payload.get("dados", [])
            if not items:
                break
            for item in items:
                description = item.get("descricao", "")
                if not _is_nominal_description(description):
                    continue
                voted_at = parse_datetime(item.get("dataHoraRegistro")) or parse_datetime(f"{item.get('data', '')}T00:00:00")
                Voting.objects.update_or_create(
                    external_id=str(item["id"]),
                    defaults={
                        "title": description[:300],
                        "voted_at": timezone.make_aware(voted_at) if voted_at and timezone.is_naive(voted_at) else voted_at,
                        "result": description[:120],
                        "level": LegislativeLevel.FEDERAL,
                        "source": data_source,
                        "official_url": item.get("uri", ""),
                    },
                )
                imported += 1
            if not any(link.get("rel") == "next" for link in payload.get("links", [])):
                break
            page += 1
    return imported


def ensure_voting_projects(votings, api=None):
    api = api or CamaraAPI()
    for voting in votings:
        if voting.project_id:
            continue
        try:
            refresh_voting_context(voting, api)
        except requests.RequestException:
            continue
    return votings


@transaction.atomic
def hydrate_project(project, api=None):
    api = api or CamaraAPI()
    detail = api.get(f"proposicoes/{project.external_id}").get("dados", {})
    project = upsert_project({**detail, "id": project.external_id}, project.source or source(), project.author)
    authors = api.get(f"proposicoes/{project.external_id}/autores").get("dados", [])
    for author_data in authors:
        uri = author_data.get("uri", "")
        if "/deputados/" not in uri:
            continue
        deputy_id = uri.rstrip("/").rsplit("/", 1)[-1]
        deputy_data = api.get(f"deputados/{deputy_id}").get("dados", {})
        if deputy_data:
            project.author = upsert_parliamentarian(deputy_data, project.source or source())
            project.save(update_fields=["author"])
            break
    tramitacoes = api.get(f"proposicoes/{project.external_id}/tramitacoes").get("dados", [])[-20:]
    project.processing_events.all().delete()
    events = []
    for item in tramitacoes:
        raw_datetime = item.get("dataHora") or f"{item.get('data', '')}T{item.get('hora', '00:00:00')}"
        occurred_at = parse_datetime(raw_datetime)
        if not occurred_at:
            continue
        events.append(
            ProcessingEvent(
                project=project,
                occurred_at=timezone.make_aware(occurred_at) if timezone.is_naive(occurred_at) else occurred_at,
                description=(item.get("descricaoTramitacao") or item.get("despacho") or "Movimentação legislativa")[:300],
                source=project.source,
            )
        )
    ProcessingEvent.objects.bulk_create(events)
    return project


def _voting_explanation(voting, detail):
    parts = []
    if voting.project:
        parts.append(
            f"Os deputados votaram o {voting.project.code}, que trata do seguinte: "
            f"{voting.project.title.rstrip('.')}."
        )
    decision = detail.get("descricao") or voting.title
    if decision:
        parts.append(f"O que foi decidido nesta sessão: {decision.rstrip('.')}.")
    procedure = detail.get("descUltimaAberturaVotacao") or ""
    if procedure:
        parts.append(f"A Câmara registrou o seguinte procedimento: {procedure.rstrip('.')}.")
    return " ".join(parts)


def apply_voting_context(voting, detail, data_source=None):
    affected = detail.get("proposicoesAfetadas") or []
    if affected:
        voting.project = upsert_project(affected[0], data_source or voting.source or source())
    voting.title = (detail.get("descricao") or voting.title)[:300]
    voting.organ = (detail.get("siglaOrgao") or "")[:60]
    voting.procedure = (detail.get("descUltimaAberturaVotacao") or "")[:240]
    last_presentation = detail.get("ultimaApresentacaoProposicao") or {}
    voting.subject_detail = last_presentation.get("descricao") or ""
    voting.description = _voting_explanation(voting, detail)
    approval = detail.get("aprovacao")
    voting.result = "Aprovado" if approval == 1 else "Não aprovado" if approval == 0 else voting.result
    voting.save(
        update_fields=[
            "project",
            "title",
            "organ",
            "procedure",
            "subject_detail",
            "description",
            "result",
        ]
    )
    return voting


def refresh_voting_context(voting, api=None):
    api = api or CamaraAPI()
    detail = api.get(f"votacoes/{voting.external_id}").get("dados", {})
    return apply_voting_context(voting, detail)


def refresh_project_context(project, api=None):
    api = api or CamaraAPI()
    detail = api.get(f"proposicoes/{project.external_id}").get("dados", {})
    if not detail:
        return project
    return upsert_project({**detail, "id": project.external_id}, project.source or source())


PROPOSITION_KINDS = {
    "": {"label": "Todos", "siglas": None},
    "PL": {"label": "PL", "siglas": ["PL"]},
    "PEC": {"label": "PEC", "siglas": ["PEC"]},
    "PLP": {"label": "PLP", "siglas": ["PLP"]},
    "EMENDA": {"label": "Emendas", "siglas": ["EMC", "EMP", "EMR", "EMA", "EMD", "ERD", "ERP", "ERS", "ERL", "SBE", "SBT"]},
    "REQ": {"label": "Requerimentos", "siglas": ["REQ", "RIC", "RCP"]},
    "PDL": {"label": "Decretos", "siglas": ["PDC", "PDL"]},
}

KIND_PLAIN = {
    "PL": "Este é um projeto de lei ordinária. Se a Câmara e o Senado aprovarem e o presidente sancionar, a regra vira lei.",
    "PEC": "Esta é uma proposta de emenda à Constituição. Não cria uma lei comum: tenta mudar o próprio texto da Constituição, o que exige maioria qualificada.",
    "PLP": "Este é um projeto de lei complementar. Serve para regulamentar um ponto que a Constituição deixou expressamente para esse tipo de lei.",
    "PDC": "Este é um projeto de decreto legislativo. A decisão cabe ao Congresso e não passa por sanção presidencial.",
    "PDL": "Este é um projeto de decreto legislativo. A decisão cabe ao Congresso e não passa por sanção presidencial.",
    "REQ": "Este é um requerimento. Não cria lei: pede uma providência da Câmara, como informação, urgência, homenagem ou inclusão de pauta.",
    "RIC": "Este é um requerimento de informação. O deputado cobra dados oficiais de um ministério ou órgão do Executivo.",
    "RCP": "Este é um requerimento de instituição de comissão parlamentar. Propõe criar um colegiado para investigar ou acompanhar um tema.",
}


def proposition_sigla(project):
    return (project.code or "").split(" ", 1)[0].upper()


def explain_project(project):
    sigla = proposition_sigla(project)
    kind = KIND_PLAIN.get(sigla)
    if not kind and (sigla.startswith("EM") or sigla in {"SBE", "SBT"}):
        kind = "Esta é uma emenda. Não abre um projeto novo: altera o texto de outra proposição que já está em discussão."
    ementa = (project.description or project.title or "").strip().rstrip(".")
    parts = []
    if kind:
        parts.append(kind)
    if ementa:
        start = ementa[0].lower() + ementa[1:] if ementa[:1].isupper() else ementa
        parts.append(f"Na prática, o texto {start}.")
    if project.keywords:
        subjects = project.keywords.replace(";", ",").strip(" .")
        parts.append(f"Os temas envolvidos são {subjects}.")
    if project.situation:
        parts.append(f"Na Câmara, a situação atual é: {project.situation}.")
    if project.regime:
        parts.append(f"O regime de tramitação registrado é {project.regime}.")
    return " ".join(parts) or "A Câmara ainda não publicou uma ementa clara para esta proposição."


def _page_number_from_href(href, fallback=1):
    query = parse_qs(urlparse(href or "").query)
    try:
        return max(int(query.get("pagina", [fallback])[0]), 1)
    except (TypeError, ValueError):
        return fallback


def _count_author_propositions(api, parliamentarian, year, kind=""):
    params = {
        "idDeputadoAutor": parliamentarian.external_id,
        "ano": year,
        "ordem": "DESC",
        "ordenarPor": "id",
        "itens": 1,
        "pagina": 1,
    }
    siglas = PROPOSITION_KINDS.get(kind, PROPOSITION_KINDS[""])["siglas"]
    if siglas:
        params["siglaTipo"] = siglas
    payload = api.get("proposicoes", params)
    links = payload.get("links", [])
    last = next((link.get("href") for link in links if link.get("rel") == "last"), "")
    if last:
        return _page_number_from_href(last, 1 if payload.get("dados") else 0)
    return 1 if payload.get("dados") else 0


def fetch_author_propositions(parliamentarian, year, page=1, per_page=7, kind="", api=None):
    """Busca sob demanda as proposições do autor no ano, 7 por vez, com data e total de páginas."""
    api = api or CamaraAPI()
    params = {
        "idDeputadoAutor": parliamentarian.external_id,
        "ano": year,
        "ordem": "DESC",
        "ordenarPor": "id",
        "itens": per_page,
        "pagina": max(page, 1),
    }
    siglas = PROPOSITION_KINDS.get(kind, PROPOSITION_KINDS[""])["siglas"]
    if siglas:
        params["siglaTipo"] = siglas
    payload = api.get("proposicoes", params)
    data_source = parliamentarian.source or source()
    projects = [upsert_project(item, data_source, author=parliamentarian) for item in payload.get("dados", [])]
    total_items = _count_author_propositions(api, parliamentarian, year, kind)
    total_pages = max(ceil(total_items / per_page), 1) if total_items else 1
    return projects, total_pages


@transaction.atomic
def hydrate_voting(voting, api=None):
    api = api or CamaraAPI()
    detail = api.get(f"votacoes/{voting.external_id}").get("dados", {})
    apply_voting_context(voting, detail)
    votes = api.get(f"votacoes/{voting.external_id}/votos").get("dados", [])
    for vote_data in votes:
        deputy = vote_data.get("deputado_") or vote_data.get("deputado") or {}
        if not deputy.get("id"):
            continue
        parliamentarian = upsert_parliamentarian(deputy, voting.source or source())
        choice = {
            "Sim": Vote.Choice.YES,
            "Não": Vote.Choice.NO,
            "Abstenção": Vote.Choice.ABSTENTION,
        }.get(vote_data.get("tipoVoto"), Vote.Choice.ABSENT)
        Vote.objects.update_or_create(
            voting=voting,
            parliamentarian=parliamentarian,
            defaults={"choice": choice},
        )
    return voting


def sync_expenses(api, data_source, start_year, end_year):
    total = 0
    for deputy in Parliamentarian.objects.filter(level=LegislativeLevel.FEDERAL, is_mock=False):
        for year in range(start_year, end_year + 1):
            for item in api.all(f"deputados/{deputy.external_id}/despesas", {"ano": year}):
                value = Decimal(str(item.get("valorLiquido", item.get("valorDocumento", 0)) or 0))
                external_id = f"{deputy.external_id}-{item.get('codDocumento', item.get('numDocumento', total))}-{year}"
                Expense.objects.update_or_create(external_id=external_id, defaults={"parliamentarian": deputy, "year": year, "month": item.get("mes"), "category": item.get("tipoDespesa", ""), "supplier": item.get("nomeFornecedor", ""), "document_number": str(item.get("numDocumento", "")), "value": value, "document_url": item.get("urlDocumento", ""), "source": data_source})
                total += 1
    return total
