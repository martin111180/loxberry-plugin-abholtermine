# Entwicklung und Releases

## Aufbau

* `plugin/`: genau der Inhalt des LoxBerry-Plugin-ZIPs (im ZIP liegt er im Ordner `abholtermine/`)
  * `bin/umweltprofis.py`: Abfrage von www.umweltprofis.at (Auswahllisten, Wohnort setzen, Termine parsen)
  * `bin/termine.py`: berechnet aus den Terminen alle MQTT-Werte (Tage, morgen, Erinnerung, Texte)
  * `bin/abholtermine_bridge.py`: Dienst (Abruf alle `refresh_hours`, MQTT, Live-Status für die Weboberfläche)
  * `bin/service.sh`: start/stop/restart/status/watchdog; startet die Bridge als Benutzer `loxberry`
  * `webfrontend/htmlauth/index.php`: Weboberfläche (Status, Einstellungen, Adress-Auswahl über Proxy zu umweltprofis.at)
  * `config/abholtermine.json`: Standardkonfiguration; `config/requirements.txt`: Python-Pakete (exakt gepinnt)
  * `icons/`: Logo „unsere Umwelt Profis“ von www.umweltprofis.at, auf 64/128/256/512 px skaliert
* `tests/`: Unit-Tests mit Ausschnitten der echten Website (`tests/fixtures/`)
* `tools/build_zip.py`: baut `dist/loxberry-plugin-abholtermine-<version>.zip`

Alle Textdateien brauchen LF-Zeilenenden (`.gitattributes` erzwingt das; `build_zip.py` bricht bei CRLF ab).

## Datenquelle

Die OpenData-Schnittstelle `data.umweltprofis.at/opendata/AppointmentService/AppointmentService.asmx` (XML-Link mit
Key) war bei der Entwicklung (11/2026) nicht erreichbar (HTTP 503). Verwendet werden die Abfragen der Website:

1. `was_wie_zu_entsorgen_ist.html?tx_ecxumweltprofis_pi2[controller]=Location&tx_ecxumweltprofis_pi2[action]=ajaxGetCities|ajaxGetStreets|ajaxGetHouseNumbers&…[district|city|street]=<id>` → JSON `[{uid, title}]`
2. `wann_wird_mein_abfall_abgeholt.html` laden (Sitzungs-Cookie + versteckte Formularfelder), Formular
   `choose-location-form` mit Bezirk/Ort/Straße/Hausnummer per POST senden → Antwort `redirect: <Bezirksseite>`
3. Bezirksseite laden: Tabelle `div-row-table` (row1 Abfallart, row2 Datum, row3 Intervall) für laufenden und nächsten Monat

Ändert sich die Website, schlagen die Tests mit neuen Fixtures fehl bzw. die Bridge meldet `bridge/error`.

## Laufzeit

* Python-Umgebung: `REPLACELBPDATADIR/venv` (von `postinstall.sh` mit `python3 -m venv` angelegt)
* Termin-Zwischenspeicher: `REPLACELBPDATADIR/termine.json` (übersteht Neustarts, verhindert unnötige Abrufe)
* Live-Status: `/dev/shm/loxberry-plugin-abholtermine/status.json`
* „Jetzt abrufen“ in der Weboberfläche legt `REPLACELBPDATADIR/refresh.flag` an, die Bridge holt dann sofort neu
* Log: `REPLACELBPLOGDIR/abholtermine.log`

## Tests

```bash
python -m unittest discover -s tests -v
python tools/build_zip.py
python plugin/bin/umweltprofis.py cities 9      # Live-Abfrage: Orte im Bezirk Linz-Land
```

Die CI (`.github/workflows/release.yml`) führt Tests und Build mit Python 3.11 (LoxBerry 3) und 3.13 (LoxBerry 4)
aus und prüft Shell- und PHP-Syntax.

## Neue Version veröffentlichen

1. In `plugin/plugin.cfg` `VERSION=` erhöhen und committen.
2. `git tag v0.1.1 && git push origin main --tags`
3. Der Workflow prüft, ob Tag und `VERSION` übereinstimmen, baut das ZIP, legt das GitHub-Release an und
   setzt `release.cfg` auf `main`. Ab dann bieten die LoxBerrys das Update an.

## Pfade

Nie `/opt/loxberry` fest eintragen. Stattdessen die Platzhalter verwenden, die der LoxBerry bei der
Installation ersetzt: `REPLACELBHOMEDIR`, `REPLACELBPBINDIR`, `REPLACELBPCONFIGDIR`, `REPLACELBPDATADIR`,
`REPLACELBPLOGDIR`.
