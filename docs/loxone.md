# Abholtermine im Loxone Miniserver

## Grundidee: rechnen im Plugin, nicht im Miniserver

Datumsrechnen ist in Loxone Config mühsam (Datum vergleichen, „morgen“ erkennen, Texte zusammensetzen).
Das Plugin liefert deshalb **fertige Werte**:

* `…/<art>/tage` – Tage bis zur nächsten Abholung (0 heute, 1 morgen, -1 nichts im Zeitraum)
* `…/morgen`, `…/heute` – 0/1 über alle Abfallarten
* `…/erinnerung` – wird am Vortag zur eingestellten Uhrzeit (Standard 18:00) **1** und um Mitternacht wieder 0.
  Die **steigende Flanke** ist der Auslöser für die Push-Nachricht – genau einmal pro Abholtag, auch nach einem
  Neustart des Miniservers (der Wert ist *retained*).
* `…/erinnerung_text`, `…/naechste_text`, `…/liste`, `…/<art>/text` – fertige Texte für App und Nachricht

## 1. MQTT Gateway

Im Plugin unter *Einstellungen → Abfallarten* zuerst die Tonnen abwählen, die es nicht gibt. Für eine
Übersichtskachel mit Push-Erinnerung reichen fünf Topics:

```
abholtermine/naechste_tage
abholtermine/naechste_text
abholtermine/erinnerung
abholtermine/erinnerung_text
abholtermine/bridge/error
```

Diese Zeilen in LoxBerry → *MQTT Gateway* → *Subscriptions* eintragen. Unter *Incoming Overview* erscheinen dann
die Eingänge, z. B. `abholtermine_naechste_text`. Wer zusätzlich je Tonne eine Anzeige möchte, abonniert
`abholtermine/<art>/tage` und `abholtermine/<art>/text`; wer alles möchte, `abholtermine/#`.

In Loxone Config (Virtuelle Eingänge des MQTT Gateways) anlegen:

| Eingang | Typ | Verwendung |
|---|---|---|
| `abholtermine_erinnerung` | Virtueller Eingang (digital) | Auslöser Push-Nachricht |
| `abholtermine_erinnerung_text` | Virtueller Texteingang | Text der Push-Nachricht |
| `abholtermine_morgen` | Virtueller Eingang (digital) | optional, z. B. Hinweis-LED (zusätzlich abonnieren) |
| `abholtermine_naechste_tage` | Virtueller Eingang (analog) | Farbe des Übersichts-Statusbausteins |
| `abholtermine_naechste_text` | Virtueller Texteingang | Anzeige in der App |
| `abholtermine_liste` | Virtueller Texteingang | optional, alle Termine in einer Zeile (zusätzlich abonnieren) |
| `abholtermine_<art>_tage` | Virtueller Eingang (analog) | Anzeige je Tonne, Statusbaustein |
| `abholtermine_<art>_text` | Virtueller Texteingang | Anzeige je Tonne |
| `abholtermine_bridge_error` | Virtueller Texteingang | Überwachung (alles außer `OK` = Problem) |

## 2. Anzeige in der App (Vorschlag)

**Variante A – einfach:** die Texteingänge `abholtermine_naechste_text` und `abholtermine_liste` direkt in der
Visualisierung anzeigen (Kategorie z. B. „Haushalt“, Raum „Außen“). Ergebnis in der App:

* Nächste Abholung: *Restabfall übermorgen (Di 17.11.)*
* Termine: *Di 17.11. Restabfall · Fr 20.11. Gelber Sack · Mi 25.11. Bioabfall*

**Variante B – je Tonne ein Eintrag:** pro Abfallart den Texteingang `abholtermine_<art>_text` anzeigen
(„Restabfall: morgen (Di 17.11.)“). Wer Farben möchte, nimmt einen **Statusbaustein** mit
`abholtermine_<art>_tage` am Eingang und Bedingungen wie

| Bedingung | Statustext | Farbe |
|---|---|---|
| AI1 = 0 | heute | rot |
| AI1 = 1 | morgen rausstellen | orange |
| AI1 > 1 | in `<v1>` Tagen | grün |
| AI1 = -1 | kein Termin | grau |

**Variante C – Datum als Loxone-Zeit:** `abholtermine_<art>_datum_lox` ist ein Datum in Loxone-Zeit
(Sekunden seit 1.1.2009). Mit einem Datums-Anzeigeformat am virtuellen Eingang wird es in der App als Datum
angezeigt; damit lässt sich auch in eigener Logik weiterrechnen. Für die meisten Anzeigen reichen aber die
fertigen Texte.

## 3. Erinnerung am Vortag

* `abholtermine_erinnerung` (digital) auf den Auslöser eines Bausteins für **Push-Benachrichtigungen**
  legen (in Loxone Config je nach Version „Benachrichtigung“/„Push-Benachrichtigung“ oder die
  Benachrichtigungsfunktion des Statusbausteins).
* Als Nachrichtentext `abholtermine_erinnerung_text` verwenden → *„Morgen wird abgeholt: Restabfall und Gelber Sack“*.
* Die Uhrzeit stellt man im Plugin ein (Einstellungen → *Erinnerung am Vortag um*), nicht im Miniserver.

## Weitere Ideen

* **Licht-Hinweis:** `abholtermine_morgen` auf eine Status-LED beim Eingang oder als kurzes Blinken der
  Außenbeleuchtung beim Heimkommen – dann vergisst man die Tonne nicht, auch ohne aufs Handy zu schauen.
* **Erinnerung quittieren:** in Loxone einen Taster „Tonne steht draußen“ (z. B. ein Merker, der beim Wechsel von
  `abholtermine_erinnerung` auf 1 gesetzt und per Taster zurückgesetzt wird). Ist der Merker um 21 Uhr noch aktiv,
  eine zweite Push-Nachricht schicken.
* **Überwachung:** `abholtermine_bridge_error` ≠ `OK` länger als einen Tag → Hinweis an den Admin (Website
  von umweltprofis.at geändert oder Adresse ungültig).
* **Sofort neu abrufen:** eine beliebige Nachricht an `abholtermine/cmd/refresh` (z. B. über das MQTT Gateway).
