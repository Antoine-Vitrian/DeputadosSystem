from pathlib import Path

from django import template
from django.conf import settings
from django.templatetags.static import static

register = template.Library()


@register.simple_tag
def versioned_static(path):
    """URL do arquivo estático com a data de modificação, para o navegador não reaproveitar cache antigo."""
    url = static(path)
    for directory in settings.STATICFILES_DIRS:
        candidate = Path(directory) / path
        if candidate.exists():
            return f"{url}?v={int(candidate.stat().st_mtime)}"
    return url
