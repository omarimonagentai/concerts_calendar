#!/usr/bin/env python3
"""
update_concerts.py
==================
Llegeix artists.json, descarrega les fonts configurades per a cada artista
i genera un informe de concerts candidats per actualitzar concerts.json.

Ús bàsic:
  pip install requests beautifulsoup4
  python update_concerts.py                 # informe (no escriu res)
  python update_concerts.py --artist Madness   # només un artista
  python update_concerts.py --report informe.txt   # desa l'informe a un fitxer
  python update_concerts.py --merge nous.json --apply   # afegeix concerts d'un JSON

Format del JSON per --merge (llista de concerts amb la mateixa estructura
que concerts.json):
  [
    {
      "id": "madness-009",
      "artist": "Madness",
      "title": "Madness 2026 – ...",
      "date": "2026-09-05",
      "venue": "...",
      "city": "...",
      "country": "...",
      "country_code": "..",
      "url": "...",
      "notes": ""
    }
  ]

Què fa:
  1. Llegeix artists.json (llista d'artistes a seguir).
  2. Per cada artista actiu, descarrega les fonts (HTML) i busca patrons
     de dates per detectar concerts potencials.
  3. Mostra un informe amb el que ha trobat i actualitza el camp
     "last_checked" de cada artista.
  4. Si s'usa --merge fitxer.json, fusiona els concerts nous a
     concerts.json (sense duplicar IDs).

NOTA: el parsing automàtic de cada font és aproximat. Per a actualitzacions
fiables, utilitza --merge passant un JSON revisat manualment (o generat
per Claude a partir de l'informe).
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import datetime

# ── Configuració ──────────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTISTS_FILE = os.path.join(BASE_DIR, "artists.json")
CONCERTS_FILE = os.path.join(BASE_DIR, "concerts.json")
LAST_UPDATE_FILE = os.path.join(BASE_DIR, "darrera_actualitzacio.txt")

# Patró per detectar dates a HTML: 2026-06-15, 15/06/2026, 15 Jun 2026, etc.
DATE_PATTERNS = [
    r"\b(\d{4}-\d{2}-\d{2})\b",                                  # 2026-06-15
    r"\b(\d{1,2}/\d{1,2}/\d{4})\b",                              # 15/06/2026
    r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b",
    r"\b(\d{1,2}\s+(?:gen|feb|mar|abr|mai|jun|jul|ago|set|oct|nov|des)[a-z]*\s+\d{4})\b",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def now_iso():
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.now(ZoneInfo("Europe/Madrid"))
    except Exception:
        dt = datetime.now().astimezone()
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


def fetch_url(url, timeout=15):
    """Descarrega una URL. Retorna text o None si falla."""
    try:
        import requests
    except ImportError:
        print("  [!] Cal instal·lar 'requests' i 'beautifulsoup4':")
        print("      pip install requests beautifulsoup4")
        sys.exit(1)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ConcertsCalendarBot/1.0)"
    }
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        return r.text
    except Exception as e:
        return None


def extract_text(html):
    """Treu tags HTML i deixa text net."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        # Fallback molt bàsic
        return re.sub(r"<[^>]+>", " ", html)
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)


def slugify(text):
    """Genera un slug ASCII a partir d'un text."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def find_dates(text):
    """Retorna llista de dates trobades al text."""
    found = []
    for pattern in DATE_PATTERNS:
        for m in re.findall(pattern, text, flags=re.IGNORECASE):
            if m not in found:
                found.append(m)
    return found


# ── Comandaments ──────────────────────────────────────────────────────────────

def cmd_report(args):
    """Genera l'informe de fonts per a cada artista."""
    artists_data = load_json(ARTISTS_FILE)
    if not artists_data:
        print(f"[!] No s'ha trobat {ARTISTS_FILE}")
        return 1

    concerts_data = load_json(CONCERTS_FILE, default={"concerts": []})
    existing_by_artist = {}
    for c in concerts_data.get("concerts", []):
        existing_by_artist.setdefault(c["artist"], []).append(c)

    lines = []
    lines.append("=" * 60)
    lines.append(f"  Informe Concerts Calendar – {now_iso()}")
    lines.append("=" * 60)

    artists = artists_data["artists"]
    if args.artist:
        artists = [a for a in artists if a["name"].lower() == args.artist.lower()]
        if not artists:
            print(f"[!] Artista '{args.artist}' no trobat a artists.json")
            return 1

    for artist in artists:
        name = artist["name"]
        existing = existing_by_artist.get(name, [])
        future_existing = [c for c in existing if c["date"] >= datetime.now().strftime("%Y-%m-%d")]

        lines.append("")
        lines.append(f"── {name} {'(actiu)' if artist.get('active') else '(en seguiment)'}")
        lines.append(f"   Concerts a concerts.json: {len(existing)} (futurs: {len(future_existing)})")
        if artist.get("notes"):
            lines.append(f"   Notes: {artist['notes']}")
        lines.append(f"   Última comprovació: {artist.get('last_checked') or 'mai'}")

        for src in artist.get("sources", []):
            lines.append(f"   • Font: {src}")
            html = fetch_url(src)
            if html is None:
                lines.append(f"       [!] No s'ha pogut descarregar")
                continue
            text = extract_text(html)
            dates = find_dates(text)
            if dates:
                lines.append(f"       Dates detectades ({len(dates)}): {', '.join(dates[:10])}{'...' if len(dates) > 10 else ''}")
            else:
                lines.append(f"       Cap data detectada al text descarregat")

        # Marca com a comprovat
        artist["last_checked"] = now_iso()

    lines.append("")
    lines.append("=" * 60)
    lines.append("FI. Per afegir concerts revisats, utilitza:")
    lines.append("    python update_concerts.py --merge candidats.json --apply")
    lines.append("=" * 60)

    output = "\n".join(lines)
    print(output)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"\nInforme desat a: {args.report}")

    if args.apply:
        save_json(ARTISTS_FILE, artists_data)
        print(f"\n'last_checked' actualitzat a artists.json")

    return 0


def cmd_merge(args):
    """Fusiona concerts d'un fitxer JSON dins concerts.json."""
    if not os.path.exists(args.merge):
        print(f"[!] No s'ha trobat el fitxer: {args.merge}")
        return 1

    new_concerts = load_json(args.merge)
    if isinstance(new_concerts, dict) and "concerts" in new_concerts:
        new_concerts = new_concerts["concerts"]
    if not isinstance(new_concerts, list):
        print(f"[!] El fitxer ha de ser una llista de concerts (o dict amb clau 'concerts')")
        return 1

    data = load_json(CONCERTS_FILE, default={"concerts": [], "sources": []})
    existing_ids = {c["id"] for c in data["concerts"]}

    added = []
    updated = []
    skipped = []

    for c in new_concerts:
        cid = c.get("id")
        if not cid:
            skipped.append(f"(sense id) {c.get('artist', '?')} – {c.get('date', '?')}")
            continue
        # Validar camps mínims
        required = ["artist", "title", "date", "venue", "city", "country", "country_code"]
        missing = [f for f in required if not c.get(f)]
        if missing:
            skipped.append(f"{cid} (falta: {', '.join(missing)})")
            continue
        # Validar data
        try:
            datetime.strptime(c["date"], "%Y-%m-%d")
        except (ValueError, TypeError):
            skipped.append(f"{cid} (data invàlida: {c.get('date')})")
            continue

        c.setdefault("url", "")
        c.setdefault("notes", "")

        if cid in existing_ids:
            # Actualitzar el concert existent
            for i, old in enumerate(data["concerts"]):
                if old["id"] == cid:
                    data["concerts"][i] = c
                    updated.append(cid)
                    break
        else:
            data["concerts"].append(c)
            existing_ids.add(cid)
            added.append(cid)

    print(f"  Afegits:      {len(added)}")
    for cid in added:
        print(f"    + {cid}")
    print(f"  Actualitzats: {len(updated)}")
    for cid in updated:
        print(f"    ~ {cid}")
    if skipped:
        print(f"  Ignorats:     {len(skipped)}")
        for s in skipped:
            print(f"    ! {s}")

    if args.apply:
        data["last_updated"] = now_iso()
        save_json(CONCERTS_FILE, data)
        with open(LAST_UPDATE_FILE, "w", encoding="utf-8") as f:
            f.write(now_iso())
        print(f"\nconcerts.json actualitzat ({len(data['concerts'])} concerts en total)")
    else:
        print("\n[Mode simulació] Cap canvi escrit. Afegeix --apply per aplicar.")

    return 0


# ── Mode automàtic (GitHub Actions) ──────────────────────────────────────────

# Mapa de noms de país (diverses llengües) → codi ISO 2 lletres
_COUNTRY_TO_CODE = {
    "united kingdom": "GB", "uk": "GB", "england": "GB",
    "scotland": "GB", "wales": "GB", "great britain": "GB",
    "spain": "ES", "españa": "ES", "espagne": "ES",
    "italy": "IT", "italia": "IT", "italie": "IT",
    "germany": "DE", "deutschland": "DE", "allemagne": "DE",
    "france": "FR",
    "netherlands": "NL", "holland": "NL", "nederland": "NL",
    "belgium": "BE", "belgique": "BE", "belgië": "BE",
    "switzerland": "CH", "schweiz": "CH", "suisse": "CH",
    "austria": "AT", "österreich": "AT",
    "portugal": "PT",
    "denmark": "DK", "danmark": "DK",
    "sweden": "SE", "sverige": "SE",
    "norway": "NO", "norge": "NO",
    "finland": "FI", "suomi": "FI",
    "ireland": "IE", "éire": "IE",
    "usa": "US", "united states": "US", "u.s.a.": "US",
    "canada": "CA",
    "australia": "AU",
    "japan": "JP", "japon": "JP",
    "brazil": "BR", "brasil": "BR",
    "mexico": "MX", "méxico": "MX",
    "argentina": "AR",
    "slovenia": "SI", "slowenien": "SI",
    "luxembourg": "LU",
    "poland": "PL", "polska": "PL",
    "czech republic": "CZ", "czechia": "CZ", "česko": "CZ",
    "hungary": "HU", "magyarország": "HU",
    "romania": "RO",
    "serbia": "RS",
    "croatia": "HR", "hrvatska": "HR",
    "greece": "GR", "hellas": "GR",
    "turkey": "TR", "türkiye": "TR",
    "israel": "IL",
    "new zealand": "NZ",
    "south africa": "ZA",
}

_CODE_TO_COUNTRY = {
    "GB": "UK", "ES": "Espanya", "IT": "Itàlia", "DE": "Alemanya",
    "FR": "França", "NL": "Països Baixos", "BE": "Bèlgica",
    "CH": "Suïssa", "AT": "Àustria", "PT": "Portugal",
    "DK": "Dinamarca", "SE": "Suècia", "NO": "Noruega",
    "FI": "Finlàndia", "IE": "Irlanda", "US": "EUA",
    "CA": "Canadà", "AU": "Austràlia", "JP": "Japó",
    "BR": "Brasil", "MX": "Mèxic", "AR": "Argentina",
    "SI": "Eslovènia", "LU": "Luxemburg", "PL": "Polònia",
    "CZ": "República Txeca", "HU": "Hongria", "RO": "Romania",
    "RS": "Sèrbia", "HR": "Croàcia", "GR": "Grècia",
    "TR": "Turquia", "IL": "Israel", "ZA": "Sud-àfrica",
    "NZ": "Nova Zelanda",
}


def _normalize_country(raw):
    """Retorna (country_display, country_code) a partir d'un string lliure."""
    if not raw:
        return "", ""
    s = raw.strip()
    # Pot venir directament com a codi ISO
    if re.match(r'^[A-Z]{2}$', s):
        return _CODE_TO_COUNTRY.get(s, s), s
    code = _COUNTRY_TO_CODE.get(s.lower(), "")
    display = _CODE_TO_COUNTRY.get(code, s) if code else s
    return display, code


def _abs_url(href, base_url):
    """Converteix un href relatiu en URL absoluta."""
    if not href:
        return ""
    if href.startswith("http"):
        return href
    try:
        from urllib.parse import urlparse
        p = urlparse(base_url)
        return f"{p.scheme}://{p.netloc}{href}" if href.startswith("/") else ""
    except Exception:
        return ""


def _parse_iso_date(raw):
    """Intenta convertir un string de data a YYYY-MM-DD. Retorna '' si falla."""
    if not raw:
        return ""
    # Ja en format ISO (pot tenir hora)
    m = re.match(r'(\d{4}-\d{2}-\d{2})', raw)
    if m:
        return m.group(1)
    return ""


def extract_concerts_structured(artist_name, source_url, html, today_str):
    """
    Extreu concerts d'una pàgina HTML sense cap API externa.

    Estratègia:
      1. JSON-LD (schema.org MusicEvent / Event) — molt fiable en llocs moderns.
      2. Meta/microdata amb itemprop="startDate".
      3. Fallback: cerca dates ISO en text i intenta extreure venue/city proper.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results = []

    # ── 1. JSON-LD ────────────────────────────────────────────────────────────
    EVENT_TYPES = {"MusicEvent", "Event", "TheaterEvent", "SocialEvent",
                   "Festival", "ScreeningEvent"}

    def _from_jsonld_item(item):
        if not isinstance(item, dict):
            return None
        t = item.get("@type", "")
        if isinstance(t, list):
            t = t[0] if t else ""
        if t not in EVENT_TYPES:
            return None
        date_str = _parse_iso_date(
            item.get("startDate") or item.get("startTime") or ""
        )
        if not date_str or date_str < today_str:
            return None

        loc = item.get("location") or {}
        if isinstance(loc, str):
            venue, city, country_raw = loc, "", ""
        else:
            venue = loc.get("name", "")
            addr = loc.get("address") or {}
            if isinstance(addr, str):
                city, country_raw = addr, ""
            else:
                city = (addr.get("addressLocality")
                        or addr.get("addressRegion") or "")
                country_raw = (addr.get("addressCountry")
                               or addr.get("name") or "")

        country_display, country_code = _normalize_country(country_raw)

        link = item.get("url") or item.get("@id") or ""
        if not str(link).startswith("http"):
            link = ""

        name = item.get("name") or f"{artist_name} @ {venue}, {city}"
        return {
            "date": date_str,
            "venue": venue,
            "city": city,
            "country": country_display,
            "country_code": country_code,
            "title": name,
            "url": str(link),
            "notes": "",
        }

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue
        queue = data if isinstance(data, list) else [data]
        visited = set()
        while queue:
            item = queue.pop(0)
            if not isinstance(item, dict):
                continue
            iid = id(item)
            if iid in visited:
                continue
            visited.add(iid)
            # Expandeix @graph i ItemList
            if "@graph" in item:
                queue.extend(item["@graph"] if isinstance(item["@graph"], list) else [])
            if item.get("@type") == "ItemList":
                elems = item.get("itemListElement", [])
                queue.extend(elems if isinstance(elems, list) else [])
            c = _from_jsonld_item(item)
            if c:
                results.append(c)

    if results:
        return results

    # ── 2. Microdata itemprop="startDate" ─────────────────────────────────────
    for el in soup.find_all(attrs={"itemprop": "startDate"}):
        date_str = _parse_iso_date(
            el.get("content") or el.get("datetime") or el.get_text()
        )
        if not date_str or date_str < today_str:
            continue
        # Cerca el contenidor de l'event
        parent = el.parent
        for _ in range(4):
            if parent is None:
                break
            if parent.get("itemtype", "").endswith(("MusicEvent", "Event")):
                break
            parent = parent.parent
        block = parent or el.parent

        venue_el = block.find(attrs={"itemprop": "name"}) if block else None
        venue = venue_el.get_text(strip=True) if venue_el else ""

        loc_el = block.find(attrs={"itemprop": "addressLocality"}) if block else None
        city = loc_el.get_text(strip=True) if loc_el else ""

        cty_el = block.find(attrs={"itemprop": "addressCountry"}) if block else None
        country_raw = cty_el.get("content") or (cty_el.get_text(strip=True) if cty_el else "")
        country_display, country_code = _normalize_country(country_raw)

        link_el = block.find("a", href=True) if block else None
        url = _abs_url(link_el["href"], source_url) if link_el else ""

        results.append({
            "date": date_str,
            "venue": venue,
            "city": city,
            "country": country_display,
            "country_code": country_code,
            "title": f"{artist_name} @ {venue}, {city}".strip(", @"),
            "url": url,
            "notes": "",
        })

    if results:
        return results

    # ── 3. Fallback: dates ISO en el text de cada bloc ─────────────────────────
    date_re = re.compile(r'\b(\d{4}-\d{2}-\d{2})\b')
    seen = set()

    # Cerca en elements de llista / fila de taula / article
    blocks = soup.find_all(
        lambda t: t.name in ("li", "tr", "article", "div", "section")
        and date_re.search(t.get_text())
        and not any(
            date_re.search(child.get_text())
            for child in t.find_all(
                lambda c: c.name in ("li", "tr", "article"), recursive=False
            )
        )
    )

    for block in blocks:
        text = block.get_text(" ", strip=True)
        m = date_re.search(text)
        if not m:
            continue
        date_str = m.group(1)
        if date_str < today_str or date_str in seen:
            continue
        seen.add(date_str)

        link_el = block.find("a", href=True)
        url = _abs_url(link_el["href"], source_url) if link_el else ""

        # Intenta identificar país en el text
        country_display, country_code = "", ""
        for cname, ccode in _COUNTRY_TO_CODE.items():
            if re.search(r'\b' + re.escape(cname) + r'\b', text, re.IGNORECASE):
                country_display = _CODE_TO_COUNTRY.get(ccode, cname.title())
                country_code = ccode
                break

        clean = date_re.sub("", text).strip()
        results.append({
            "date": date_str,
            "venue": "",
            "city": "",
            "country": country_display,
            "country_code": country_code,
            "title": f"{artist_name} concert",
            "url": url,
            "notes": clean[:200],
        })

    return results


def cmd_auto(args):
    """Mode automàtic per a GitHub Actions: sincronitza artistes i extreu concerts."""
    artists_data = load_json(ARTISTS_FILE)
    if not artists_data:
        print(f"[!] No s'ha trobat {ARTISTS_FILE}")
        return 1

    data = load_json(CONCERTS_FILE, default={"concerts": [], "sources": []})
    today_str = datetime.now().strftime("%Y-%m-%d")

    # Elimina concerts d'artistes que ja no existeixen a artists.json
    known_artists = {a["name"] for a in artists_data["artists"]}
    before = len(data["concerts"])
    data["concerts"] = [c for c in data["concerts"] if c.get("artist") in known_artists]
    removed = before - len(data["concerts"])
    if removed:
        print(f"[sync] Eliminats {removed} concerts d'artistes desconeguts")

    # Elimina concerts passats
    before = len(data["concerts"])
    data["concerts"] = [c for c in data["concerts"] if c.get("date", "") >= today_str]
    expired = before - len(data["concerts"])
    if expired:
        print(f"[sync] Eliminats {expired} concerts passats")

    existing_keys = {
        (c["artist"], c["date"], c.get("city", "").lower())
        for c in data["concerts"]
    }
    existing_ids = {c["id"] for c in data["concerts"]}

    added_total = 0
    artists = artists_data["artists"]
    if args.artist:
        artists = [a for a in artists if a["name"].lower() == args.artist.lower()]

    for artist in artists:
        if not artist.get("active"):
            continue

        name = artist["name"]
        print(f"\n── {name}")

        for src in artist.get("sources", []):
            print(f"   Descarregant: {src}")
            html = fetch_url(src)
            if html is None:
                print(f"   [!] No s'ha pogut descarregar")
                continue

            candidates = extract_concerts_structured(name, src, html, today_str)
            print(f"   Candidats trobats: {len(candidates)}")

            for c in candidates:
                key = (name, c["date"], c.get("city", "").lower())
                if key in existing_keys:
                    continue

                city_slug = slugify(c.get("city") or "unknown")
                date_slug = c["date"]
                base_id = f"{slugify(name)}-{date_slug}-{city_slug}"
                uid = base_id
                suffix = 2
                while uid in existing_ids:
                    uid = f"{base_id}-{suffix}"
                    suffix += 1

                new_concert = {
                    "id": uid,
                    "artist": name,
                    "title": c.get("title") or f"{name} @ {c.get('venue','')}, {c.get('city','')}",
                    "date": c["date"],
                    "venue": c.get("venue", ""),
                    "city": c.get("city", ""),
                    "country": c.get("country", ""),
                    "country_code": c.get("country_code", ""),
                    "url": c.get("url", ""),
                    "notes": c.get("notes", ""),
                }
                data["concerts"].append(new_concert)
                existing_keys.add(key)
                existing_ids.add(uid)
                added_total += 1
                print(f"   + {uid}")

        artist["last_checked"] = now_iso()

    print(f"\n[resultat] Afegits {added_total} concerts nous")
    print(f"[resultat] Total concerts: {len(data['concerts'])}")

    if args.apply:
        data["last_updated"] = now_iso()
        save_json(CONCERTS_FILE, data)
        save_json(ARTISTS_FILE, artists_data)
        with open(LAST_UPDATE_FILE, "w", encoding="utf-8") as f:
            f.write(now_iso())
        print(f"\nconcerts.json actualitzat")
    else:
        print("\n[Mode simulació] Cap canvi escrit. Afegeix --apply per aplicar.")

    return 0


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Actualitza concerts.json a partir de la llista d'artistes."
    )
    parser.add_argument("--artist", help="Limita a un sol artista")
    parser.add_argument("--report", help="Desa l'informe a un fitxer de text")
    parser.add_argument("--merge", help="Fusiona concerts d'un JSON a concerts.json")
    parser.add_argument("--apply", action="store_true",
                        help="Aplica els canvis (sense això, mode simulació)")
    parser.add_argument("--auto", action="store_true",
                        help="Mode automàtic: extreu concerts via IA (per a GitHub Actions)")
    args = parser.parse_args()

    if args.merge:
        return cmd_merge(args)
    if args.auto:
        return cmd_auto(args)
    return cmd_report(args)


if __name__ == "__main__":
    sys.exit(main())
