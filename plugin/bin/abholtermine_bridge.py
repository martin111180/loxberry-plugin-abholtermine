#!/usr/bin/env python3
"""Abholtermine (Umweltprofis) -> MQTT Bridge für LoxBerry.

Holt die Abfuhrtermine für die eingestellte Adresse von www.umweltprofis.at (alle `refresh_hours` Stunden,
nach jeder Änderung der Einstellungen und auf Anforderung) und veröffentlicht fertige Werte per MQTT.
Das MQTT Gateway des LoxBerry leitet sie an den Miniserver.

Topics (Basis-Topic standardmäßig "abholtermine"):
    <base>/heute, <base>/morgen             1 = an diesem Tag wird etwas abgeholt
    <base>/heute_text, <base>/morgen_text   z. B. "Restabfall und Gelber Sack", sonst "-"
    <base>/erinnerung                       1 = morgen Abholung und Erinnerungszeit erreicht (bis Mitternacht)
    <base>/erinnerung_text                  "Morgen wird abgeholt: Restabfall"
    <base>/naechste_tage|_datum|_datum_lox|_text   nächster Termin
    <base>/liste, <base>/anzahl             alle Termine im Zeitraum
    <base>/<abfallart>/tage|datum|datum_lox|text|heute|morgen
    <base>/bridge/status                    online / offline (Last Will)
    <base>/bridge/error                     Fehlertext, "OK" wenn alles in Ordnung
    <base>/bridge/last_update               Zeitpunkt des letzten erfolgreichen Abrufs (Text)
    <base>/cmd/refresh                      (abonniert) beliebige Nachricht = sofort neu abrufen

Werte werden retained gesendet, nur bei Änderung; alle `republish_seconds` wird alles erneut gesendet.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import socket
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Set

import paho.mqtt.client as mqtt

import termine
import umweltprofis

PLUGIN = "abholtermine"
LBHOMEDIR = os.environ.get("LBHOMEDIR", "REPLACELBHOMEDIR")  # Platzhalter, ersetzt der LoxBerry bei der Installation
# Live-Status für die Weboberfläche: im RAM (tmpfs). Gleicher Pfad wie $at_statusfile in index.php.
STATUS_FILE = "/dev/shm/loxberry-plugin-abholtermine/status.json"
LOOP_SECONDS = 15
RETRY_MINUTES = [5, 15, 30, 60]  # Wartezeit nach fehlgeschlagenem Abruf (wächst bis 1 h)
RETAINED_SCAN_SECONDS = 5.0

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "location": {
        "district": "", "district_name": "",
        "city": "", "city_name": "",
        "street": "", "street_name": "",
        "house": "", "house_name": "",
    },
    "days": 14,
    "reminder_time": "18:00",
    "filters": {},
    "refresh_hours": 6,
    "topic": "abholtermine",
    "republish_seconds": 300,
    "loglevel": "INFO",
    "mqtt": {"use_loxberry": True, "host": "localhost", "port": 1883, "user": "", "password": ""},
}

log = logging.getLogger("abholtermine_bridge")


# ----------------------------------------------------------------------------
# Konfiguration
# ----------------------------------------------------------------------------


def deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict) and key != "filters":
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            return deep_merge(DEFAULT_CONFIG, json.load(fh))
    except FileNotFoundError:
        log.warning("Konfiguration %s nicht gefunden – verwende Standardwerte", path)
        return dict(DEFAULT_CONFIG)


def location_complete(loc: dict) -> bool:
    return all(str(loc.get(k) or "") for k in ("district", "city", "street", "house"))


def location_key(loc: dict) -> str:
    return "/".join(str(loc.get(k) or "") for k in ("district", "city", "street", "house"))


def loxberry_mqtt_settings() -> dict:
    """Broker-Zugangsdaten des LoxBerry (ab LB 3.0 in general.json, sonst MQTT-Gateway-Plugin)."""
    try:
        with open(f"{LBHOMEDIR}/config/system/general.json", encoding="utf-8") as fh:
            m = json.load(fh).get("Mqtt") or {}
        if m.get("Brokerhost"):
            return {
                "host": m.get("Brokerhost", "localhost"),
                "port": int(m.get("Brokerport") or 1883),
                "user": m.get("Brokeruser", ""),
                "password": m.get("Brokerpass", ""),
            }
    except (OSError, ValueError):
        pass
    try:
        gw_dir = f"{LBHOMEDIR}/config/plugins/mqttgateway"
        with open(f"{gw_dir}/mqtt.json", encoding="utf-8") as fh:
            addr = json.load(fh)["Main"]["brokeraddress"]
        with open(f"{gw_dir}/cred.json", encoding="utf-8") as fh:
            cred = json.load(fh)["Credentials"]
        host, _, port = addr.partition(":")
        return {
            "host": host or "localhost",
            "port": int(port or 1883),
            "user": cred.get("brokeruser", ""),
            "password": cred.get("brokerpass", ""),
        }
    except (OSError, ValueError, KeyError):
        pass
    log.warning("Keine LoxBerry-MQTT-Zugangsdaten gefunden – verwende localhost:1883 ohne Login")
    return {"host": "localhost", "port": 1883, "user": "", "password": ""}


# ----------------------------------------------------------------------------
# MQTT
# ----------------------------------------------------------------------------


class MqttPublisher:
    def __init__(self, cfg: dict, base: str, on_refresh) -> None:
        self.base = base
        self._cache: Dict[str, str] = {}
        self._lock = threading.Lock()
        self._scan: Optional[Set[str]] = None
        self._on_refresh = on_refresh
        self.connected = False
        settings = loxberry_mqtt_settings() if cfg["mqtt"].get("use_loxberry", True) else cfg["mqtt"]
        self.host = settings.get("host") or "localhost"
        self.port = int(settings.get("port") or 1883)
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"loxberry-abholtermine-{socket.gethostname()}",
        )
        if settings.get("user"):
            self.client.username_pw_set(settings["user"], settings.get("password") or None)
        self.client.will_set(f"{base}/bridge/status", "offline", qos=1, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=2, max_delay=60)

    def start(self) -> None:
        log.info("Verbinde mit MQTT-Broker %s:%s", self.host, self.port)
        self.client.connect_async(self.host, self.port, keepalive=60)
        self.client.loop_start()

    def stop(self) -> None:
        try:
            self.client.publish(f"{self.base}/bridge/status", "offline", qos=1, retain=True).wait_for_publish(3)
        except Exception:  # noqa: BLE001
            pass
        self.client.disconnect()
        self.client.loop_stop()

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            log.error("MQTT-Verbindung abgelehnt: %s", reason_code)
            return
        log.info("MQTT verbunden")
        self.connected = True
        client.publish(f"{self.base}/bridge/status", "online", qos=1, retain=True)
        client.subscribe(f"{self.base}/cmd/#")
        self.republish_all()

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        self.connected = False
        if reason_code != 0:
            log.warning("MQTT-Verbindung getrennt (%s) – versuche Reconnect", reason_code)

    def _on_message(self, client, userdata, msg) -> None:
        if msg.topic == f"{self.base}/cmd/refresh":
            if msg.retain:
                return  # alte gespeicherte Befehle nicht ausführen
            log.info("Abruf per MQTT angefordert")
            self._on_refresh()
            return
        with self._lock:
            if self._scan is not None and msg.retain and msg.payload:
                self._scan.add(msg.topic)

    def publish(self, sub_topic: str, payload: str) -> None:
        topic = f"{self.base}/{sub_topic}"
        with self._lock:
            if self._cache.get(topic) == payload:
                return
            self._cache[topic] = payload
        log.debug("%s = %s", topic, payload)
        if self.connected:
            self.client.publish(topic, payload, qos=0, retain=True)

    def republish_all(self) -> None:
        with self._lock:
            items = list(self._cache.items())
        for topic, payload in items:
            self.client.publish(topic, payload, qos=0, retain=True)

    # --- Verwaiste Topics löschen (z. B. Abfallart ausgeblendet oder Adresse geändert)

    def begin_retained_scan(self) -> None:
        with self._lock:
            self._scan = set()
        self.client.subscribe(f"{self.base}/#")

    def finish_retained_scan(self) -> List[str]:
        self.client.unsubscribe(f"{self.base}/#")
        self.client.subscribe(f"{self.base}/cmd/#")
        with self._lock:
            found, self._scan = self._scan or set(), None
            current = set(self._cache)
        keep = (f"{self.base}/bridge/", f"{self.base}/cmd/")
        stale = sorted(t for t in found - current if not t.startswith(keep))
        for topic in stale:
            self.client.publish(topic, b"", qos=1, retain=True)  # leere retained Nachricht = löschen
        return stale


# ----------------------------------------------------------------------------
# Bridge
# ----------------------------------------------------------------------------


class Bridge:
    def __init__(self, cfg: dict, status_file: str, cache_file: str, refresh_flag: str) -> None:
        self.cfg = cfg
        self.status_file = status_file
        self.cache_file = cache_file
        self.refresh_flag = refresh_flag
        self.base = str(cfg.get("topic") or PLUGIN).strip("/")
        self.stop_event = threading.Event()
        self.refresh_requested = threading.Event()
        self.mqtt = MqttPublisher(cfg, self.base, self.refresh_requested.set)
        self.data: Optional[Dict[str, Any]] = self._load_cache()
        self.error = ""
        self.failures = 0
        self.next_try = 0.0
        self.result: Dict[str, Any] = {"values": {}, "entries": []}
        self.scan_state = "pending"  # pending -> scanning -> done
        self.scan_started = 0.0

    # --- Zwischenspeicher der abgerufenen Termine (übersteht Neustarts, schont umweltprofis.at)

    def _load_cache(self) -> Optional[Dict[str, Any]]:
        try:
            with open(self.cache_file, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return None
        if data.get("location_key") != location_key(self.cfg["location"]):
            log.info("Adresse geändert – gespeicherte Termine werden verworfen")
            return None
        return data

    def _save_cache(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            tmp = self.cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, self.cache_file)
        except OSError as exc:
            log.warning("Termine konnten nicht gespeichert werden: %s", exc)

    def _needs_fetch(self, now: float) -> bool:
        if os.path.exists(self.refresh_flag):
            try:
                os.remove(self.refresh_flag)
            except OSError:
                pass
            log.info("Abruf über die Weboberfläche angefordert")
            self.refresh_requested.set()
        if self.refresh_requested.is_set():
            return True
        if now < self.next_try:
            return False
        if not self.data:
            return True
        age = now - float(self.data.get("fetched", 0))
        if age >= float(self.cfg.get("refresh_hours") or 6) * 3600:
            return True
        # Neuer Tag und der Abruf ist von gestern: Monatswechsel etc. sofort nachladen
        fetched_day = dt.date.fromtimestamp(float(self.data.get("fetched", 0)))
        return fetched_day != dt.date.today() and dt.datetime.now().hour >= 1

    def fetch(self) -> None:
        self.refresh_requested.clear()
        loc = self.cfg["location"]
        log.info("Rufe Termine ab: %s, %s %s", loc.get("city_name"), loc.get("street_name"), loc.get("house_name"))
        try:
            data = umweltprofis.fetch_calendar(loc["district"], loc["city"], loc["street"], loc["house"])
        except umweltprofis.UmweltprofisError as exc:
            self.failures += 1
            wait = RETRY_MINUTES[min(self.failures, len(RETRY_MINUTES)) - 1]
            self.next_try = time.time() + wait * 60
            self.error = f"{exc} (nächster Versuch in {wait} min)"
            log.warning("Abruf fehlgeschlagen: %s – nächster Versuch in %d min", exc, wait)
            return
        except Exception as exc:  # noqa: BLE001 – unerwartete Antwort darf die Bridge nicht beenden
            self.failures += 1
            self.next_try = time.time() + 60 * 60
            self.error = f"Unerwarteter Fehler beim Abruf: {exc}"
            log.exception("Unerwarteter Fehler beim Abruf")
            return
        data["fetched"] = time.time()
        data["location_key"] = location_key(loc)
        self.data = data
        self.failures = 0
        self.next_try = 0.0
        self.error = ""
        self._save_cache()
        log.info("%d Termine, Abfallarten: %s", len(data["entries"]),
                 ", ".join(str(t["name"]) for t in data["types"]))

    def update_values(self) -> None:
        if self.data:
            self.result = termine.compute(
                self.data,
                self.cfg.get("filters") or {},
                int(self.cfg.get("days") or 14),
                dt.datetime.now(),
                str(self.cfg.get("reminder_time") or "18:00"),
            )
            for sub_topic, payload in self.result["values"].items():
                self.mqtt.publish(sub_topic, payload)
            self.mqtt.publish("bridge/last_update",
                              dt.datetime.fromtimestamp(float(self.data["fetched"])).strftime("%d.%m.%Y %H:%M"))
        error = self.error
        if not location_complete(self.cfg["location"]):
            error = "Keine Adresse eingestellt"
        elif not self.data and not error:
            error = "Noch keine Termine abgerufen"
        self.mqtt.publish("bridge/error", error or "OK")  # leere retained Nachricht würde das Topic löschen

    def maintain_retained(self, now: float) -> None:
        if self.scan_state == "pending" and self.mqtt.connected and self.data:
            self.mqtt.begin_retained_scan()
            self.scan_state, self.scan_started = "scanning", now
        elif self.scan_state == "scanning" and now - self.scan_started >= RETAINED_SCAN_SECONDS:
            stale = self.mqtt.finish_retained_scan()
            self.scan_state = "done"
            if stale:
                log.info("Veraltete Topics gelöscht: %s", ", ".join(stale))

    def write_status(self) -> None:
        status = {
            "time": time.time(),
            "mqtt_connected": self.mqtt.connected,
            "mqtt_broker": f"{self.mqtt.host}:{self.mqtt.port}",
            "error": self.error,
            "fetched": (self.data or {}).get("fetched"),
            "source_url": (self.data or {}).get("source_url"),
            "types": (self.data or {}).get("types", []),
            "entries": self.result.get("entries", []),
            "values": self.result.get("values", {}),
            "next_try": self.next_try,
        }
        try:
            os.makedirs(os.path.dirname(self.status_file), exist_ok=True)
            tmp = self.status_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(status, fh, ensure_ascii=False)
            os.replace(tmp, self.status_file)
        except OSError as exc:
            log.debug("Status-Datei nicht schreibbar: %s", exc)

    def run(self) -> None:
        self.mqtt.start()
        self.mqtt.publish("bridge/error", "OK")
        republish = max(30, int(self.cfg.get("republish_seconds") or 300))
        last_republish = time.time()
        while not self.stop_event.is_set():
            now = time.time()
            if not location_complete(self.cfg["location"]):
                self.refresh_requested.clear()
            elif self._needs_fetch(now):
                self.fetch()
            self.update_values()
            self.maintain_retained(now)
            if now - last_republish >= republish and self.mqtt.connected:
                self.mqtt.republish_all()
                last_republish = now
            self.write_status()
            # kurz warten; ein Abruf per MQTT weckt die Schleife sofort
            self.refresh_requested.wait(LOOP_SECONDS if self.scan_state != "scanning" else 1)
        self.mqtt.stop()


# ----------------------------------------------------------------------------
# Start
# ----------------------------------------------------------------------------


def setup_logging(logfile: str, level: str) -> None:
    os.makedirs(os.path.dirname(logfile), exist_ok=True)
    handler = RotatingFileHandler(logfile, maxBytes=500_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logging.getLogger("paho").setLevel(logging.WARNING)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=f"{LBHOMEDIR}/config/plugins/{PLUGIN}/abholtermine.json")
    parser.add_argument("--log", default=f"{LBHOMEDIR}/log/plugins/{PLUGIN}/abholtermine.log")
    parser.add_argument("--status", default=STATUS_FILE)
    parser.add_argument("--cache", default=f"{LBHOMEDIR}/data/plugins/{PLUGIN}/termine.json")
    parser.add_argument("--refresh-flag", default=f"{LBHOMEDIR}/data/plugins/{PLUGIN}/refresh.flag")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(args.log, cfg.get("loglevel", "INFO"))
    log.info("Abholtermine-Bridge startet (Python %s)", sys.version.split()[0])

    bridge = Bridge(cfg, args.status, args.cache, args.refresh_flag)

    def _stop(*_):
        bridge.stop_event.set()
        bridge.refresh_requested.set()  # Warten sofort beenden

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _stop)
    try:
        bridge.run()
    except Exception:  # noqa: BLE001
        log.exception("Unerwarteter Fehler – Bridge wird beendet (der Watchdog startet sie neu)")
        return 1
    log.info("Abholtermine-Bridge beendet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
