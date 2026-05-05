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
    args = parser.parse_args()

    if args.merge:
        return cmd_merge(args)
    return cmd_report(args)


if __name__ == "__main__":
    sys.exit(main())
