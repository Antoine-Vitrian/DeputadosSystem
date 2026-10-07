from datetime import timedelta
from email.utils import parsedate_to_datetime
from html import unescape
import re
from xml.etree import ElementTree

import requests
from django.utils import timezone

from legislature.models import DailyBrief, DataSource, NewsArticle


PODER360_URL = "https://www.poder360.com.br/"
PODER360_FEED = "https://www.poder360.com.br/feed/"


def _plain_text(value):
    text = re.sub(r"<[^>]+>", " ", unescape(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _fetch_feed():
    response = requests.get(
        PODER360_FEED,
        headers={"User-Agent": "RadarLegislativo/1.0 (+leitor RSS)"},
        timeout=20,
    )
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    articles = []
    for item in root.findall("./channel/item"):
        title = _plain_text(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        description = _plain_text(item.findtext("description"))
        published = item.findtext("pubDate")
        if not title or not link:
            continue
        articles.append(
            {
                "title": title,
                "url": link,
                "summary": description or f"Notícia publicada pelo Poder360: {title}.",
                "published_at": parsedate_to_datetime(published) if published else None,
            }
        )
    return articles


def _build_daily_summary(articles, reference_date):
    headlines = [
        article["title"]
        for article in articles
        if article["published_at"]
        and timezone.localtime(article["published_at"]).date() == reference_date
    ][:8]
    if not headlines:
        return "O feed do Poder360 não apresentou notícias para esta data."
    return "Principais notícias políticas publicadas pelo Poder360: " + "; ".join(headlines) + "."


def sync_daily_news(reference_date=None, minimum=10):
    reference_date = reference_date or (timezone.localdate() - timedelta(days=1))
    articles = _fetch_feed()
    data_source, _ = DataSource.objects.update_or_create(
        identifier="poder360-rss",
        defaults={"name": "Poder360", "url": PODER360_URL},
    )
    for article in articles:
        NewsArticle.objects.update_or_create(
            url=article["url"],
            defaults={
                "title": article["title"][:300],
                "summary": article["summary"][:1200],
                "published_at": article["published_at"],
                "category": NewsArticle.Category.POLITICS,
                "source": data_source,
            },
        )
    data_source.last_synced_at = timezone.now()
    data_source.save(update_fields=["last_synced_at"])
    day_count = sum(
        1
        for article in articles
        if article["published_at"]
        and timezone.localtime(article["published_at"]).date() == reference_date
    )
    brief, _ = DailyBrief.objects.update_or_create(
        reference_date=reference_date,
        defaults={
            "summary": _build_daily_summary(articles, reference_date),
            "article_count": day_count,
        },
    )
    return brief


def news_refresh_due():
    last_sync = DataSource.objects.filter(identifier="poder360-rss").values_list(
        "last_synced_at", flat=True
    ).first()
    return not last_sync or last_sync < timezone.now() - timedelta(hours=1)
