"""Aus den abgerufenen Terminen die MQTT-Werte für den Miniserver berechnen (ohne Abhängigkeiten, testbar).

Die ganze Datumslogik passiert hier und nicht im Miniserver: Loxone bekommt fertige Werte
(Tage bis zur Abholung, morgen ja/nein, Erinnerung mit Text) und muss nichts mehr rechnen.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from typing import Dict, Iterable, List, Optional

# Loxone rechnet Zeit in Sekunden seit 1.1.2009 (Ortszeit). Ein Analogeingang mit dem Format <v.u>
# zeigt einen solchen Wert als Datum an.
LOXONE_EPOCH = dt.date(2009, 1, 1)

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
FILTER_DEFAULT = ""  # wie auf der Website: bei mehreren Intervallen das erste, sonst alle Termine
FILTER_ALL = "*"     # alle Intervalle
FILTER_NEVER = "-"   # Abfallart ausblenden
NONE_DAYS = -1       # "tage", wenn im Zeitraum kein Termin liegt


def slug(text: str) -> str:
    """Topic-Name aus einem Text: "Gelber Sack" -> "gelber_sack", "Bioabfall" -> "bioabfall".

    Muss slug() in index.php entsprechen.
    """
    text = text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "x"


def loxone_time(day: dt.date) -> int:
    return (day - LOXONE_EPOCH).days * 86400


def short_date(day: dt.date) -> str:
    return f"{WEEKDAYS[day.weekday()]} {day.strftime('%d.%m.')}"


def long_date(day: dt.date) -> str:
    return f"{WEEKDAYS[day.weekday()]}, {day.strftime('%d.%m.%Y')}"


def relative(days: int) -> str:
    if days == 0:
        return "heute"
    if days == 1:
        return "morgen"
    if days == 2:
        return "übermorgen"
    return f"in {days} Tagen"


def join_types(names: Iterable[str]) -> str:
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " und " + names[-1]


def default_interval(type_info: Dict[str, object]) -> Optional[str]:
    """Intervall, das die Website ohne Auswahl zeigt (erste Option), sonst None = alle."""
    intervals = type_info.get("intervals") or []
    return str(intervals[0]["name"]) if intervals else None  # type: ignore[index]


def select_entries(data: Dict[str, object], filters: Dict[str, str]) -> List[Dict[str, object]]:
    """Termine nach den Intervall-Einstellungen filtern; doppelte (gleiche Art, gleicher Tag) entfernen."""
    types = {str(t["name"]): t for t in data.get("types", [])}  # type: ignore[union-attr]
    result: List[Dict[str, object]] = []
    seen = set()
    for e in data.get("entries", []):  # type: ignore[union-attr]
        name = str(e["type"])
        choice = filters.get(name, FILTER_DEFAULT)
        if choice == FILTER_NEVER:
            continue
        if choice == FILTER_DEFAULT:
            wanted = default_interval(types.get(name, {}))
        elif choice == FILTER_ALL:
            wanted = None
        else:
            wanted = choice
        if wanted is not None and e.get("interval") and e["interval"] != wanted:
            continue
        key = (name, e["date"])
        if key in seen:
            continue
        seen.add(key)
        result.append(e)
    result.sort(key=lambda e: (e["date"], e["type"]))
    return result


def compute(
    data: Dict[str, object],
    filters: Dict[str, str],
    days: int,
    now: dt.datetime,
    reminder_time: str = "18:00",
) -> Dict[str, object]:
    """Alle MQTT-Werte (Topic ohne Basis -> Wert als Text) und die Terminliste für die Weboberfläche."""
    today = now.date()
    last_day = today + dt.timedelta(days=max(0, days))
    entries = [
        e for e in select_entries(data, filters)
        if today <= dt.date.fromisoformat(str(e["date"])) <= last_day
    ]
    for e in entries:
        e["days"] = (dt.date.fromisoformat(str(e["date"])) - today).days

    values: Dict[str, str] = {}

    def on(day_offset: int) -> List[str]:
        names: List[str] = []
        for e in entries:
            if e["days"] == day_offset and e["type"] not in names:
                names.append(str(e["type"]))
        return names

    today_names, tomorrow_names = on(0), on(1)
    values["heute"] = "1" if today_names else "0"
    values["heute_text"] = join_types(today_names) if today_names else "-"
    values["morgen"] = "1" if tomorrow_names else "0"
    values["morgen_text"] = join_types(tomorrow_names) if tomorrow_names else "-"

    # Erinnerung: am Vortag ab der eingestellten Uhrzeit bis Mitternacht 1 -> steigende Flanke für die Push-Nachricht
    try:
        hh, mm = (int(x) for x in reminder_time.split(":", 1))
        reminder_at = dt.time(hh, mm)
    except ValueError:
        reminder_at = dt.time(18, 0)
    reminder = bool(tomorrow_names) and now.time() >= reminder_at
    values["erinnerung"] = "1" if reminder else "0"
    values["erinnerung_text"] = f"Morgen wird abgeholt: {join_types(tomorrow_names)}" if tomorrow_names else "-"

    if entries:
        first = entries[0]
        day = dt.date.fromisoformat(str(first["date"]))
        names = on(int(first["days"]))
        values["naechste_tage"] = str(first["days"])
        values["naechste_datum"] = long_date(day)
        values["naechste_datum_lox"] = str(loxone_time(day))
        values["naechste_text"] = f"{join_types(names)} {relative(int(first['days']))} ({short_date(day)})"
    else:
        values["naechste_tage"] = str(NONE_DAYS)
        values["naechste_datum"] = "-"
        values["naechste_datum_lox"] = "0"
        values["naechste_text"] = f"Keine Abholung in den nächsten {days} Tagen"

    # Liste für einen Text-Baustein: "Di 17.11. Restabfall · Fr 20.11. Gelber Sack"
    by_day: Dict[str, List[str]] = {}
    for e in entries:
        by_day.setdefault(str(e["date"]), []).append(str(e["type"]))
    values["liste"] = " · ".join(
        f"{short_date(dt.date.fromisoformat(d))} {join_types(n)}" for d, n in by_day.items()
    ) or "-"
    values["anzahl"] = str(len(entries))

    # Je Abfallart (auch ohne Termin im Zeitraum, damit die Eingänge im Miniserver nicht hängen bleiben)
    for t in data.get("types", []):  # type: ignore[union-attr]
        name = str(t["name"])
        if filters.get(name) == FILTER_NEVER:
            continue
        key = slug(name)
        nxt = next((e for e in entries if e["type"] == name), None)
        if nxt:
            day = dt.date.fromisoformat(str(nxt["date"]))
            values[f"{key}/tage"] = str(nxt["days"])
            values[f"{key}/datum"] = long_date(day)
            values[f"{key}/datum_lox"] = str(loxone_time(day))
            values[f"{key}/text"] = f"{relative(int(nxt['days']))} ({short_date(day)})"
        else:
            values[f"{key}/tage"] = str(NONE_DAYS)
            values[f"{key}/datum"] = "-"
            values[f"{key}/datum_lox"] = "0"
            values[f"{key}/text"] = "kein Termin"
        values[f"{key}/heute"] = "1" if nxt and nxt["days"] == 0 else "0"
        values[f"{key}/morgen"] = "1" if nxt and nxt["days"] == 1 else "0"

    return {"values": values, "entries": entries}
