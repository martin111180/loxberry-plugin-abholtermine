"""Abfuhrtermine von www.umweltprofis.at (OÖ Bezirksabfallverbände) abfragen.

Die offizielle OpenData-Schnittstelle (data.umweltprofis.at) ist seit längerem nicht erreichbar. Dieses Modul
nutzt deshalb dieselben Abfragen wie der Abholkalender auf www.umweltprofis.at:

1. Auswahllisten: Bezirk -> Ort -> Straße -> Hausnummer (JSON, je ein GET)
2. Termine: Wohnort per POST im Formular "choose-location-form" speichern (Sitzungs-Cookie),
   danach liefert die Abholkalender-Seite des Bezirks die Termine des laufenden und des nächsten Monats.

Nur Standardbibliothek, damit Tests und Weboberfläche ohne zusätzliche Pakete auskommen.
"""

from __future__ import annotations

import datetime as dt
import html
import http.cookiejar
import json
import re
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

BASE_URL = "https://www.umweltprofis.at"
CALENDAR_PATH = "/allgemein/module/wann_wird_mein_abfall_abgeholt.html"
LOOKUP_PATH = "/allgemein/module/was_wie_zu_entsorgen_ist.html"
USER_AGENT = "Mozilla/5.0 (X11; Linux) LoxBerry-Plugin-Abholtermine"
TIMEOUT = 30
PLUGIN_ARG = "tx_ecxumweltprofis_pi2"

# Bezirke laut Auswahlliste der Website (value -> Name). Wird nur verwendet, wenn die Liste nicht geladen werden kann.
DISTRICTS: Dict[str, str] = {
    "2": "Braunau am Inn", "3": "Eferding", "4": "Freistadt", "5": "Gmunden", "6": "Grieskirchen",
    "7": "Kirchdorf an der Krems", "8": "Linz", "9": "Linz-Land", "10": "Perg", "11": "Ried im Innkreis",
    "12": "Rohrbach", "13": "Schärding", "14": "Steyr-Land", "15": "Steyr", "16": "Urfahr-Umgebung",
    "17": "Vöcklabruck", "18": "Wels", "19": "Wels-Land",
}


class UmweltprofisError(Exception):
    """Fehler bei der Abfrage (Netzwerk, geänderte Website, keine Termine)."""


# ----------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------


def _opener() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", USER_AGENT), ("Accept-Language", "de-AT,de;q=0.9")]
    return opener


def _read(opener: urllib.request.OpenerDirector, url: str, data: Optional[bytes] = None) -> str:
    try:
        with opener.open(url, data=data, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except OSError as exc:  # URLError, HTTPError, Timeout
        raise UmweltprofisError(f"umweltprofis.at nicht erreichbar: {exc}") from exc


def _lookup_url(action: str, **params: str) -> str:
    query = {f"{PLUGIN_ARG}[controller]": "Location", f"{PLUGIN_ARG}[action]": action}
    query.update({f"{PLUGIN_ARG}[{k}]": v for k, v in params.items()})
    return BASE_URL + LOOKUP_PATH + "?" + urllib.parse.urlencode(query)


def _lookup(action: str, **params: str) -> List[Dict[str, str]]:
    text = _read(_opener(), _lookup_url(action, **params))
    try:
        items = json.loads(text)
    except ValueError as exc:
        raise UmweltprofisError(f"Unerwartete Antwort auf {action} (keine Liste)") from exc
    if not isinstance(items, list):
        raise UmweltprofisError(f"Unerwartete Antwort auf {action}")
    return [{"id": str(i.get("uid", "")), "name": str(i.get("title", ""))} for i in items if isinstance(i, dict)]


# ----------------------------------------------------------------------------
# Auswahllisten
# ----------------------------------------------------------------------------


def get_cities(district: str) -> List[Dict[str, str]]:
    return _lookup("ajaxGetCities", district=str(district))


def get_streets(city: str) -> List[Dict[str, str]]:
    return _lookup("ajaxGetStreets", city=str(city))


def get_house_numbers(street: str) -> List[Dict[str, str]]:
    return _lookup("ajaxGetHouseNumbers", street=str(street))


# ----------------------------------------------------------------------------
# Termine
# ----------------------------------------------------------------------------

_HIDDEN_RE = re.compile(r'<input type="hidden" name="(' + PLUGIN_ARG + r'\[[^"]*)" value="([^"]*)"')
_FORM_RE = re.compile(r'<form id="choose-location-form" action="([^"]+)"')
_ROW_RE = re.compile(r'<div data-value="([^"]*)" id="row([123])-(\d+)" class="([^"]*)"')
_TYPE_SELECT_RE = re.compile(
    r'<div>([^<]+)</div>\s*</div>\s*<div class="selectrow-right">\s*<div class="form-block w-form">\s*'
    r'<select[^>]*id="type-selector-(t\d+)"[^>]*>(.*?)</select>',
    re.S,
)
_OPTION_RE = re.compile(r'<option value="([^"]*)"[^>]*>([^<]*)</option>')


def parse_form(page: str) -> Tuple[str, List[Tuple[str, str]]]:
    """Ziel und versteckte Felder (Extbase-Prüfsummen) des Wohnort-Formulars."""
    match = _FORM_RE.search(page)
    if not match:
        raise UmweltprofisError("Wohnort-Formular auf umweltprofis.at nicht gefunden (Website geändert?)")
    action = html.unescape(match.group(1))
    start = match.end()
    end = page.find("</form>", start)
    fields = [(n, html.unescape(v)) for n, v in _HIDDEN_RE.findall(page[start:end])]
    return action, fields


def parse_calendar(page: str) -> Dict[str, object]:
    """Termine und Abfallarten aus der Abholkalender-Seite lesen.

    Rückgabe: {"entries": [{date, type, type_id, interval, interval_id}], "types": [{id, name, intervals}]}
    Jede Tabellenzeile besteht aus drei Spalten (row1 = Abfallart, row2 = Datum, row3 = Intervall).
    """
    rows: Dict[str, Dict[str, str]] = {}
    for value, col, num, cls in _ROW_RE.findall(page):
        row = rows.setdefault(num, {})
        value = html.unescape(value).strip()
        if col == "1":
            row["type"] = value
            m = re.search(r"waste-type-(t\d+)", cls)
            row["type_id"] = m.group(1) if m else ""
            m = re.search(r"interval-type-(o\d+)", cls)
            row["interval_id"] = m.group(1) if m else ""
        elif col == "2":
            row["date"] = value
        else:
            row["interval"] = value

    entries = []
    for num in sorted(rows, key=int):
        row = rows[num]
        try:
            day = dt.datetime.strptime(row.get("date", ""), "%d.%m.%Y").date()
        except ValueError:
            continue
        entries.append({
            "date": day.isoformat(),
            "type": row.get("type", ""),
            "type_id": row.get("type_id", ""),
            "interval": row.get("interval", ""),
            "interval_id": row.get("interval_id", ""),
        })

    types: List[Dict[str, object]] = []
    for name, type_id, options in _TYPE_SELECT_RE.findall(page):
        intervals = [
            {"id": v, "name": html.unescape(t).strip()}
            for v, t in _OPTION_RE.findall(options)
            if v.startswith("o")
        ]
        types.append({"id": type_id, "name": html.unescape(name).strip(), "intervals": intervals})
    # Abfallarten, die nur in der Tabelle vorkommen, ergänzen
    known = {t["id"] for t in types}
    for e in entries:
        if e["type_id"] not in known:
            known.add(e["type_id"])
            types.append({"id": e["type_id"], "name": e["type"], "intervals": []})
    return {"entries": entries, "types": types}


def fetch_calendar(district: str, city: str, street: str, house: str) -> Dict[str, object]:
    """Wohnort setzen und die Termine (laufender + nächster Monat) holen."""
    opener = _opener()
    page = _read(opener, BASE_URL + CALENDAR_PATH)
    action, fields = parse_form(page)
    fields += [
        (f"{PLUGIN_ARG}[location][district]", str(district)),
        (f"{PLUGIN_ARG}[location][city]", str(city)),
        (f"{PLUGIN_ARG}[location][street]", str(street)),
        (f"{PLUGIN_ARG}[location][houseNumber]", str(house)),
    ]
    answer = _read(opener, urllib.parse.urljoin(BASE_URL, action), urllib.parse.urlencode(fields).encode())
    target = BASE_URL + CALENDAR_PATH
    if "redirect:" in answer:
        target = answer.split("redirect:", 1)[1].strip().split()[0]
    if not target.startswith(BASE_URL + "/"):
        raise UmweltprofisError(f"Unerwartete Weiterleitung: {target[:100]}")
    data = parse_calendar(_read(opener, target))
    if not data["types"]:
        raise UmweltprofisError("Keine Abfallarten gefunden – Adresse prüfen (oder Website geändert)")
    data["source_url"] = target
    return data


def get_intervals_for(types: List[Dict[str, object]]) -> Dict[str, List[str]]:
    """Abfallart -> Liste der Intervallnamen (für die Weboberfläche)."""
    return {str(t["name"]): [str(i["name"]) for i in t["intervals"]] for t in types}  # type: ignore[index]


if __name__ == "__main__":  # kleiner Test von der Kommandozeile
    import sys

    if len(sys.argv) == 5:
        print(json.dumps(fetch_calendar(*sys.argv[1:5]), ensure_ascii=False, indent=2))
    elif len(sys.argv) == 3 and sys.argv[1] in ("cities", "streets", "houses"):
        fn = {"cities": get_cities, "streets": get_streets, "houses": get_house_numbers}[sys.argv[1]]
        print(json.dumps(fn(sys.argv[2]), ensure_ascii=False, indent=2))
    else:
        print("Verwendung: umweltprofis.py cities <bezirk> | streets <ort> | houses <straße> | <bezirk> <ort> <straße> <haus>")
