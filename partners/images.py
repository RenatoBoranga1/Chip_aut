"""Image metadata only: never evidence for vehicle identity or scanner support."""

import re
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

IMAGE_FIELDS = ("primary_image_url", "image_source", "image_last_seen_at")
PLACEHOLDER = re.compile(
    r"placeholder|sem[-_ ]?foto|no[-_ ]?(?:photo|image)|loading|spacer|transparent|(?:^|[/_. -])logo(?:[/_. -]|$)|wrmotos-[12]x",
    re.I,
)


def image_url(raw, base_url):
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 2048:
        return None
    raw = raw.strip()
    if any(ord(c) < 32 for c in raw) or "\\" in raw:
        return None
    try:
        parsed = urlsplit(urljoin(base_url, raw))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        if parsed.port not in {None, 80, 443} or PLACEHOLDER.search(unquote(parsed.path)):
            return None
        return urlunsplit(parsed._replace(fragment=""))
    except ValueError:
        return None


def candidates(node):
    # Real lazy-load targets precede src (often a transparent loading image).
    for attr in ("data-src", "data-lazy-src", "data-srcset", "srcset", "src"):
        value = node.get(attr)
        if not isinstance(value, str):
            continue
        if "srcset" in attr:
            values = [v.strip().split() for v in value.split(",") if v.strip()]

            def rank(parts):
                try:
                    return float(parts[1][:-1]) if len(parts) > 1 else 1
                except ValueError:
                    return float("inf")

            # Smallest supplied variant: we do not invent CDN resizing parameters.
            yield from (parts[0] for parts in sorted(values, key=rank))
        else:
            yield value
    for match in re.finditer(r"background-image\s*:\s*url\(\s*['\"]?([^'\")]+)", node.get("style", ""), re.I):
        yield match.group(1).strip()


def extract_image(root, base_url):
    rejected = set()
    nodes = [root, *root.select("img, source, [style]")]
    for node in nodes:
        label = " ".join([node.get("alt", ""), " ".join(node.get("class", []))])
        for raw in candidates(node):
            if PLACEHOLDER.search(label) or PLACEHOLDER.search(unquote(raw)):
                rejected.add(raw)
                continue
            url = image_url(raw, base_url)
            if url:
                return url, len(rejected)
    return None, len(rejected)


def extract_detail_image(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    # Observed WR gallery. Never choose a random page image (logo or related ad).
    root = soup.select_one("a.fancybox.img-1") or soup.select_one("a.fancybox")
    if root:
        return extract_image(root, page_url)
    meta = soup.select_one('meta[property="og:image"]')
    raw = meta.get("content", "") if meta else ""
    return image_url(raw, page_url), int(bool(PLACEHOLDER.search(raw)))
