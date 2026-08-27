"""
Einfache dateibasierte Zwischenspeicherung mit Ablaufzeit (TTL).

Der Grund fuer dieses Modul: Die In-Memory-Caches in spotify_module.py
(Diskografie, Interpreten-Aufloesung) gehen bei jedem Neustart der App
verloren - das passiert im Dev-Modus haeufig (Flasks automatischer Neustart
bei Code-Aenderungen, Terminal geschlossen und neu geoeffnet, etc.). Sucht
man dann erneut nach einem Interpreten mit sehr umfangreicher Diskografie
(z.B. "Die drei ???" mit 200+ Folgen), wird der komplette, teure Crawl
erneut ausgefuehrt - und genau das kann Spotifys Rate-Limit fuer
Development-Mode-Apps ausloesen (siehe Chat-Verlauf).

Diese Datei-Zwischenspeicherung ueberlebt Neustarts: Einmal geladene Daten
bleiben fuer die eingestellte Ablaufzeit (Standard: 24 Stunden) gueltig,
unabhaengig davon, wie oft die App neu gestartet wird.
"""
import json
import os
import time


class DiskCache:
    def __init__(self, path, ttl_seconds=24 * 3600):
        self.path = path
        self.ttl_seconds = ttl_seconds
        self._data = self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        now = time.time()
        # Abgelaufene Eintraege gleich beim Laden aussortieren, damit die
        # Datei nicht unbegrenzt waechst.
        return {
            key: entry for key, entry in raw.items()
            if isinstance(entry, dict) and now - entry.get("cached_at", 0) < self.ttl_seconds
        }

    def get(self, key):
        entry = self._data.get(key)
        if not entry:
            return None
        if time.time() - entry.get("cached_at", 0) > self.ttl_seconds:
            del self._data[key]
            return None
        return entry.get("value")

    def set(self, key, value):
        self._data[key] = {"value": value, "cached_at": time.time()}
        self._save()

    def _save(self):
        try:
            tmp_path = self.path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f)
            os.replace(tmp_path, self.path)
        except OSError:
            pass  # Zwischenspeicherung ist ein Komfort-Feature, kein Muss
