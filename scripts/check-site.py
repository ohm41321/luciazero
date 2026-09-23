#!/usr/bin/env python3
"""Search and link checks for the GitHub Pages site under site/.

Usage: check-site.py [SITE_DIR]   (default: <repo>/site)

Every page must carry the metadata a search engine reads (title, description,
one canonical URL, reciprocal hreflang, Open Graph, parseable JSON-LD), every
local link must resolve, the sitemap must list exactly the canonical URLs, and
the skill count the pages state must match skills/catalog.txt. The Pages
workflow runs this before deploying; ./test.sh runs it in the packaging gate.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = "https://ohm41321.github.io/luciazero/"
# page file -> (html lang, canonical URL)
PAGES = {
    "index.html": ("en", BASE),
    "th/index.html": ("th", BASE + "th/"),
}
ALTERNATES = {"en": BASE, "th": BASE + "th/", "x-default": BASE}
SKILL_COUNT = {"en": r"\b(\d+) skills\b", "th": r"skill (\d+) ตัว"}


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lang = None
        self.title = ""
        self.meta: dict[str, list[str]] = {}
        self.canonical: list[str] = []
        self.alternates: dict[str, str] = {}
        self.refs: list[str] = []
        self.ids: set[str] = set()
        self.h1 = 0
        self.images: list[dict[str, str | None]] = []
        self.jsonld: list[str] = []
        self.text: list[str] = []
        self._in = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "title":
            self._in = "title"
        elif tag == "h1":
            self.h1 += 1
        elif tag == "meta":
            key = a.get("name") or a.get("property")
            if key:
                self.meta.setdefault(key, []).append(a.get("content") or "")
        elif tag == "link":
            rel = (a.get("rel") or "").split()
            if "canonical" in rel:
                self.canonical.append(a.get("href") or "")
            elif "alternate" in rel and a.get("hreflang"):
                self.alternates[a["hreflang"]] = a.get("href") or ""
            elif a.get("href") and "preconnect" not in rel:
                self.refs.append(a["href"])
        elif tag == "script" and a.get("type") == "application/ld+json":
            self._in = "jsonld"
            self.jsonld.append("")
        elif tag == "script":
            self._in = "script"
        if tag == "img":
            self.images.append(a)
        if tag in ("a", "img", "script") and (a.get("href") or a.get("src")):
            self.refs.append(a.get("href") or a.get("src"))

    def handle_endtag(self, tag):
        if tag in ("title", "script"):
            self._in = None

    def handle_data(self, data):
        if self._in == "title":
            self.title += data
        elif self._in == "jsonld":
            self.jsonld[-1] += data
        elif self._in is None:
            self.text.append(data)


def local_target(site: pathlib.Path, page: str, ref: str) -> pathlib.Path | None:
    """Map a same-site reference to the file it serves, or None if external."""
    if ref.startswith(BASE):
        rel = ref[len(BASE):]
    elif re.match(r"^[a-z][a-z0-9+.-]*:", ref, re.I) or ref.startswith("//"):
        return None
    else:
        rel = str(pathlib.PurePosixPath(page).parent / ref)
    path = unquote(urlsplit(rel).path)
    target = (site / path).resolve()
    if path == "" or path.endswith("/") or target.is_dir():
        target = target / "index.html"
    return target


def check_page(site: pathlib.Path, name: str, lang: str, url: str, skills: list[str]) -> list[str]:
    problems: list[str] = []
    bad = lambda msg: problems.append(f"{name}: {msg}")  # noqa: E731
    p = Page()
    p.feed((site / name).read_text(encoding="utf-8"))

    if p.lang != lang:
        bad(f'<html lang="{p.lang}">, expected "{lang}"')
    title = p.title.strip()
    if "Luciazero" not in title or len(title) > 65:
        bad(f"title must name Luciazero and stay within 65 characters: {title!r}")
    desc = p.meta.get("description", [])
    if len(desc) != 1 or not 70 <= len(desc[0]) <= 160:
        bad(f"needs one meta description of 70-160 characters, found {[len(d) for d in desc]}")
    if p.canonical != [url]:
        bad(f"canonical must be exactly [{url}], found {p.canonical}")
    if p.alternates != ALTERNATES:
        bad(f"hreflang alternates {p.alternates} != {ALTERNATES}")
    if p.meta.get("og:url") != [url]:
        bad(f"og:url {p.meta.get('og:url')} != canonical {url}")
    for key in ("og:title", "og:description", "og:image", "og:site_name"):
        if len(p.meta.get(key, [])) != 1 or not p.meta[key][0]:
            bad(f"needs exactly one non-empty {key}")
    for image in p.meta.get("og:image", []):
        target = local_target(site, name, image) if image.startswith(BASE) else None
        if target is None or not target.is_file():
            bad(f"og:image {image!r} must be an absolute URL to a file in the site")
    if p.meta.get("twitter:card") != ["summary_large_image"]:
        bad("twitter:card must be summary_large_image")
    if p.h1 != 1:
        bad(f"needs exactly one <h1>, found {p.h1}")
    for img in p.images:
        if not img.get("alt") or not img.get("width") or not img.get("height"):
            bad(f"<img src={img.get('src')!r}> needs alt, width and height")

    if not p.jsonld:
        bad("no JSON-LD block")
    for block in p.jsonld:
        try:
            data = json.loads(block)
        except json.JSONDecodeError as err:
            bad(f"JSON-LD does not parse: {err}")
            continue
        nodes = data.get("@graph", [data])
        if not any(n.get("name") == "Luciazero" and n.get("url") == BASE for n in nodes):
            bad(f"JSON-LD has no node named Luciazero with url {BASE}")

    for ref in p.refs:
        if ref.startswith("#"):
            if ref[1:] not in p.ids:
                bad(f"fragment {ref} has no matching id")
            continue
        target = local_target(site, name, ref)
        if target is not None and not target.is_file():
            bad(f"{ref} does not resolve to a file in the site")

    text = " ".join(" ".join(p.text).split())
    counts = re.findall(SKILL_COUNT[lang], text)
    if not counts:
        bad("no longer states its skill count")
    elif any(int(n) != len(skills) for n in counts):
        bad(f"states {sorted(set(counts))} skills, the catalog has {len(skills)}")
    missing = [s for s in skills if f"/{s}" not in text]
    if missing:
        bad(f"does not list cataloged skills {missing}")
    return problems


def main() -> int:
    site = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else ROOT / "site"
    skills = [line.strip() for line in (ROOT / "skills/catalog.txt").read_text().splitlines()
              if line.strip() and not line.lstrip().startswith("#")]
    problems: list[str] = []

    found = sorted(str(f.relative_to(site)) for f in site.rglob("*.html"))
    if found != sorted(PAGES):
        problems.append(f"site pages {found} != checked pages {sorted(PAGES)}; register new pages in PAGES")
    for name, (lang, url) in PAGES.items():
        if (site / name).is_file():
            problems += check_page(site, name, lang, url, skills)

    try:
        tree = ET.parse(site / "sitemap.xml")
        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = sorted(loc.text.strip() for loc in tree.getroot().findall("s:url/s:loc", ns))
        if locs != sorted(url for _, url in PAGES.values()):
            problems.append(f"sitemap.xml lists {locs}, expected the canonical URLs")
    except (OSError, ET.ParseError) as err:
        problems.append(f"sitemap.xml unreadable: {err}")

    for manifest in ("package.json", ".claude-plugin/plugin.json"):
        homepage = json.loads((ROOT / manifest).read_text()).get("homepage")
        if homepage != BASE:
            problems.append(f"{manifest} homepage {homepage!r} != {BASE}")

    if problems:
        print("\n".join(f"FAIL: {msg}" for msg in problems), file=sys.stderr)
        return 1
    print(f"ok  site ({len(PAGES)} pages: metadata, hreflang, links, sitemap, {len(skills)} skills)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
