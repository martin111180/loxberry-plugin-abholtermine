# CLAUDE.md

LoxBerry-Plugin, das die Müll-Abfuhrtermine von www.umweltprofis.at (OÖ Bezirksabfallverbände) für eine Adresse
abruft und fertig berechnete Werte per MQTT an den LoxBerry-Broker schickt (→ MQTT Gateway → Loxone Miniserver).
Aufbau wie die Schwester-Plugins `../loxberry-plugin-hargassner` und `../loxberry-plugin-mammotion`.

* Sprache: Deutsch (UI, Logs, Doku, Commit-Nachrichten)
* Plugin-Inhalt liegt in `plugin/`, Release-Ablauf in `docs/entwicklung.md`
* Vor jedem Commit: `bash -n` für Shell-Skripte, `python -m unittest discover -s tests` und `python tools/build_zip.py` müssen durchlaufen
* Versionsnummer nur in `plugin/plugin.cfg` ändern; `release.cfg` pflegt der Workflow
* `[AUTHOR]` in `plugin/plugin.cfg` nie ändern (LoxBerry erkennt das Plugin daran)
* Keine festen `/opt/loxberry`-Pfade – LoxBerry-Platzhalter wie `REPLACELBPBINDIR` verwenden
* Python-Abhängigkeiten exakt pinnen; Updates kommen über Dependabot-PRs. `umweltprofis.py` und `termine.py` nur mit Standardbibliothek
* Texte der Weboberfläche nur in `plugin/templates/lang/language_de.ini` und `language_en.ini` – beide immer gemeinsam pflegen
* Datumslogik gehört in `termine.py` (getestet), nicht in den Miniserver
* MQTT-Texte nie leer senden (`-`), leere retained Nachrichten löschen das Topic
* Was doppelt existiert, gleich halten: `slug()` in Python und PHP, `DEFAULT_CONFIG`/`$at_defaults`/`config/abholtermine.json`, `STATUS_FILE`/`$at_statusfile`, `DISTRICTS`/`$at_districts`
* Keine automatischen MQTT-Abos: welche Topics an den Miniserver gehen, entscheidet der Nutzer im MQTT Gateway
* Keine echten Adressen von Nutzern in Repo-Dateien (Fixtures/Tests verwenden eine beliebige Testadresse)
