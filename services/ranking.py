import requests
from django.core.cache import cache
from django.utils.text import slugify
from urllib.parse import urlencode


BASE_URL = "https://ranking.org.br"


def fetch_parliamentarian_score(parliamentarian):
    """Consulta pontuação, partido e UF pela API pública do Ranking."""
    identities = dict.fromkeys(
        value.strip()
        for value in (parliamentarian.name, parliamentarian.civil_name)
        if value and value.strip()
    )
    headers = {"Accept": "application/json", "User-Agent": "RadarLegislativo/1.0"}

    for identity in identities:
        identity_slug = slugify(identity)
        if not identity_slug:
            continue
        cache_key = f"ranking-score-v2:{identity_slug}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        query = urlencode({
            "busca": identity,
            "current_tab": 0,
            "page": 1,
            "per_page": 24,
            "ordenar_por": "pontuacao",
            "nome": identity,
        })
        response = requests.get(
            f"{BASE_URL}/api/filter-items-ranking?{query}",
            headers=headers,
            timeout=(5, 15),
        )
        response.raise_for_status()
        payload = response.json()
        candidates = payload.get("items", []) if isinstance(payload, dict) else []
        matched = next(
            (
                item for item in candidates
                if isinstance(item, dict)
                and identity_slug in {
                    slugify(item.get("nome", "")),
                    slugify(item.get("nome_eleitoral", "")),
                    slugify(item.get("nome_civil", "")),
                }
            ),
            None,
        )
        if not matched:
            continue

        composition = matched.get("composicao_pontuacao") or {}
        score = composition.get("pontuacao") if isinstance(composition, dict) else None
        if not isinstance(score, (int, float)):
            continue

        slug = matched.get("slug") or identity_slug
        result = {
            "score": score,
            "url": f"{BASE_URL}/perfil/{slug}",
            "party": matched.get("partido") or "",
            "state": matched.get("uf") or "",
        }
        cache.set(cache_key, result, 60 * 60 * 6)
        return result
    return None
