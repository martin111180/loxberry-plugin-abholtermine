# LoxBerry-Plugin: Abholtermine Umweltprofis → MQTT → Miniserver

Holt die Müll-Abfuhrtermine der oberösterreichischen Bezirksabfallverbände von
[umweltprofis.at](https://www.umweltprofis.at) für eine Adresse (Bezirk, Ort, Straße, Hausnummer) und schickt
**fertig berechnete Werte** per MQTT an den LoxBerry-Broker. Das MQTT Gateway gibt sie an den Loxone Miniserver
weiter – dort muss nichts mehr gerechnet werden: „morgen Abholung“, „in 3 Tagen“, Erinnerungs-Flanke am Vortag
und fertige Texte für App und Push-Nachricht kommen direkt vom Plugin.

* Adresse per Auswahllisten (wie auf umweltprofis.at), Auswahl der eigenen Tonnen, eigenes Intervall je Abfallart (z. B. Restabfall 2- oder 4-wöchentlich)
* Termine der nächsten *x* Tage (Standard 14), Abruf alle 6 h und sofort per Knopf oder MQTT-Befehl
* Erinnerung am Vortag zu einer einstellbaren Uhrzeit (Standard 18:00)
* Automatische Updates über die LoxBerry-Plugin-Verwaltung

> Hinweis: Die offizielle OpenData-Schnittstelle `data.umweltprofis.at` ist derzeit nicht erreichbar. Das Plugin
> verwendet dieselben Abfragen wie der Abholkalender auf www.umweltprofis.at (ein Abruf alle paar Stunden).
> Ändert sich die Website, meldet das Plugin einen Fehler in `abholtermine/bridge/error`.

## Installation

1. LoxBerry → *Plugin-Verwaltung* → diese URL eintragen und installieren:

   ```
   https://github.com/martin111180/loxberry-plugin-abholtermine/releases/latest/download/loxberry-plugin-abholtermine.zip
   ```

2. Plugin *Abholtermine Umweltprofis* öffnen → **Einstellungen** → Bezirk, Ort, Straße, Hausnummer wählen → **Speichern**.
3. Nach dem ersten Abruf in den Einstellungen bei Tonnen, die es bei dir nicht gibt, den Haken entfernen und bei
   Abfallarten mit mehreren Intervallen das eigene wählen.
4. Im **MQTT Gateway** unter *Subscriptions* die Zeilen eintragen, die das Plugin auf der Statusseite unter
   „Abos für das MQTT Gateway“ anzeigt (nur die Werte, die die Loxone-Vorlage braucht). Wer alle Werte möchte,
   abonniert `abholtermine/#`. Die Eingänge heißen dann z. B. `abholtermine_naechste_text`,
   `abholtermine_restabfall_tage`.

## MQTT-Topics

| Topic | Inhalt |
|---|---|
| `abholtermine/heute` / `morgen` | 1 = heute / morgen wird etwas abgeholt |
| `abholtermine/heute_text` / `morgen_text` | z. B. `Restabfall und Gelber Sack`, sonst `-` |
| `abholtermine/erinnerung` | **1 = morgen Abholung und Erinnerungszeit erreicht** (bis Mitternacht) – Flanke für die Push-Nachricht |
| `abholtermine/erinnerung_text` | `Morgen wird abgeholt: Restabfall` |
| `abholtermine/naechste_tage` | Tage bis zur nächsten Abholung (0 = heute, -1 = keine im Zeitraum) |
| `abholtermine/naechste_text` | `Restabfall übermorgen (Di 17.11.)` |
| `abholtermine/naechste_datum` / `naechste_datum_lox` | `Di, 17.11.2026` / Loxone-Zeit (Sekunden seit 1.1.2009) |
| `abholtermine/liste` | `Di 17.11. Restabfall · Fr 20.11. Gelber Sack · …` |
| `abholtermine/anzahl` | Anzahl Termine im Zeitraum |
| `abholtermine/<art>/tage` | Tage bis zur nächsten Abholung dieser Abfallart (-1 = keine im Zeitraum) |
| `abholtermine/<art>/text` | `in 5 Tagen (Fr 20.11.)`, `morgen (…)`, `kein Termin` |
| `abholtermine/<art>/datum` / `datum_lox` | Datum als Text / Loxone-Zeit |
| `abholtermine/<art>/heute` / `morgen` | 0/1 |
| `abholtermine/bridge/status` | `online` / `offline` (Last Will) |
| `abholtermine/bridge/error` | `OK` oder Fehlertext |
| `abholtermine/bridge/last_update` | Zeitpunkt des letzten Abrufs |
| `abholtermine/cmd/refresh` | (Befehl) beliebige Nachricht = sofort neu abrufen |

`<art>` ist der Name der Abfallart in Kleinbuchstaben: `restabfall`, `bioabfall`, `gelber_sack`, `altpapier` …
Alle Werte werden *retained* gesendet; Texte sind nie leer (`-`), damit das Topic nicht gelöscht wird.

## Loxone

Anleitung und Vorschläge für Anzeige und Erinnerung: [docs/loxone.md](docs/loxone.md)

## Entwicklung

Siehe [docs/entwicklung.md](docs/entwicklung.md).

## Hinweis

Inoffizielles Plugin, nicht von den OÖ Umwelt Profis. Das Plugin-Symbol ist das Logo „unsere Umwelt Profis“
von [umweltprofis.at](https://www.umweltprofis.at); Name und Logo gehören den jeweiligen Rechteinhabern.
