"""
Web-Radio-Modul: Sendersuche ueber die Radio-Browser-API und Wiedergabe
ueber den gemeinsamen MPVPlayer.

Radio-Browser ist ein community-betriebenes, kostenloses Senderverzeichnis
ohne Account/API-Key, das aus mehreren unabhaengigen, sich untereinander
synchronisierenden Spiegel-Servern besteht. Einzelne Server sind manchmal
kurzzeitig langsam, ueberlastet oder noch nicht ganz synchron - das aeussert
sich als faelschliches "keine Treffer", obwohl der Sender existiert (siehe
Chat-Verlauf: "bremen vier" fand beim ersten Versuch nichts, beim naechsten
schon). Deshalb wird bei einer leeren Antwort automatisch der naechste
Server in RADIO_BROWSER_HOSTS probiert, bevor wirklich "keine Treffer"
zurueckgegeben wird.

Radio-Browser listet denselben Sender oft mehrfach als getrennte Eintraege
(unterschiedliche Bitrate/Codec/Mirror, z.B. "Deutschlandfunk" als AAC 48k,
AAC 96k, MP3 128k ...). Diese werden hier zu EINER Sender-Gruppe
zusammengefasst (siehe _normalize_station_name) - die Hauptzeile spielt die
beste verfuegbare Qualitaet, eine Variantenliste erlaubt die Feinauswahl.
"""
import re

import requests

# Mehrere gleichwertige Spiegel-Server - werden der Reihe nach probiert,
# falls einer leer/fehlerhaft antwortet (siehe Modul-Docstring).
RADIO_BROWSER_HOSTS = [
    "de1.api.radio-browser.info",
    "de2.api.radio-browser.info",
    "at1.api.radio-browser.info",
]

# Bekannte Abkuerzungen, die eine reine Namenssuche sonst nicht finden wuerde,
# z.B. "dlf" kommt im Stationsnamen "Deutschlandfunk" nirgends vor.
ABBREVIATIONS = {
    "dlf": "Deutschlandfunk",
    "dkultur": "Deutschlandfunk Kultur",
    "br": "Bayerischer Rundfunk",
    "wdr": "Westdeutscher Rundfunk",
    "ndr": "Norddeutscher Rundfunk",
    "swr": "Südwestrundfunk",
    "mdr": "Mitteldeutscher Rundfunk",
    "hr": "Hessischer Rundfunk",
    "rbb": "Rundfunk Berlin-Brandenburg",
}

# Codec-/Bitrate-/Qualitaets-Angaben, die beim Gruppieren aus dem Namen
# rausgefiltert werden, damit z.B. "Deutschlandfunk" und
# "Deutschlandfunk AAC 128k" als derselbe Sender erkannt werden. Der erste
# Teil erfasst auch Faelle wie "AAC 192" OHNE "k"-Suffix (kommt bei manchen
# Radio-Browser-Eintraegen vor), aber nur direkt nach einem Codec-Namen -
# so werden nicht versehentlich echte Sender-Namen mit Zahlen drin
# (z.B. "Bayern 3", "Radio 700") kaputt-normalisiert.
_QUALITY_TOKEN_RE = re.compile(
    r"\b(aac\+?|mp3|ogg|opus|flac|hls|wma)\s*\d{0,4}\s?k?(bps)?\b"
    r"|\b\d{2,4}\s?kbps?\b|\b\d{2,4}k\b|\bhq\b|\blq\b|\bhigh\b|\blow\b|\bstereo\b|\bmono\b",
    re.IGNORECASE,
)
_PARENS_RE = re.compile(r"[\(\[][^)\]]*[\)\]]")


class WebRadioModule:
    def __init__(self, player):
        self.player = player  # gemeinsame MPVPlayer-Instanz

    def _core_name(self, name):
        """Manche Radio-Browser-Eintraege tragen den kompletten Namen als
        einen zusammengesetzten String ein, z.B. 'Deutschlandfunk | DLF |
        AAC 192' statt sauber getrennter Felder. Nur der Teil vor dem ersten
        '|' ist dabei der eigentliche Sendername - der Rest ist Abkuerzung/
        Format-Info, die weder fuer die Gruppierung noch fuer die Anzeige
        gebraucht wird."""
        return (name or "").split("|")[0].strip()

    def _normalize_station_name(self, name):
        """Gruppierungsschluessel fuer Sender-Varianten: zusammengesetzte
        Namen auf den Kernnamen kuerzen (siehe _core_name), Codec/Bitrate/
        Klammerzusaetze raus, Sonderzeichen weg, Kleinschreibung - damit
        "Deutschlandfunk", "Deutschlandfunk (AAC)", "Deutschlandfunk MP3
        128k" und "Deutschlandfunk | DLF | AAC 192" alle in dieselbe Gruppe
        fallen. Entspricht der Kernname selbst exakt einer bekannten
        Abkuerzung (z.B. "DLF" als Stationsname), wird er zusaetzlich auf
        den vollen Namen aufgeloest."""
        core = self._core_name(name)
        resolved = ABBREVIATIONS.get(core.lower(), core)
        cleaned = _PARENS_RE.sub(" ", resolved)
        cleaned = _QUALITY_TOKEN_RE.sub(" ", cleaned)
        cleaned = re.sub(r"[^\w]+", " ", cleaned, flags=re.UNICODE)
        return " ".join(cleaned.lower().split())

    def _display_name(self, name):
        """Sauberer Anzeigename: Kernname (siehe _core_name), bei bekannter
        Abkuerzung auf den vollen Namen aufgeloest."""
        core = self._core_name(name)
        return ABBREVIATIONS.get(core.lower(), core)

    def _variant_label(self, station):
        codec = (station.get("codec") or "").upper()
        bitrate = station.get("bitrate")
        parts = [p for p in [codec, f"{bitrate}k" if bitrate else None] if p]
        return " ".join(parts) if parts else "Standard"

    def _query_stations(self, term, limit):
        """Fragt Radio-Browser nach Sendern - probiert dabei der Reihe nach
        mehrere Spiegel-Server durch, falls einer leer oder fehlerhaft
        antwortet (siehe Modul-Docstring). Gibt beim ersten Server mit
        Treffern sofort zurueck; liefern alle nichts, wird eine leere Liste
        zurueckgegeben (dann gibt es wirklich keine Treffer)."""
        params = {"name": term, "limit": max(limit * 6, 60), "hidebroken": "true"}
        for host in RADIO_BROWSER_HOSTS:
            try:
                response = requests.get(
                    f"https://{host}/json/stations/search",
                    params=params,
                    timeout=6,
                )
                response.raise_for_status()
                stations = response.json()
            except (requests.RequestException, ValueError):
                continue  # dieser Server ist gerade langsam/nicht erreichbar - naechsten probieren
            if stations:
                return stations
            # Leere Antwort: koennte am Server liegen (siehe Docstring) -
            # naechsten Spiegel probieren, statt sofort aufzugeben.
        return []

    def search(self, query, limit=10):
        if not query:
            return []
        term = ABBREVIATIONS.get(query.strip().lower(), query)
        stations = self._query_stations(term, limit)

        groups = {}
        order = []
        for s in stations:
            url = s.get("url_resolved") or s.get("url")
            name = s.get("name") or ""
            if not url or not name:
                continue
            key = self._normalize_station_name(name) or name.lower()
            if key not in groups:
                groups[key] = {"name_counts": {}, "favicon": None, "country": s.get("country"), "variants": []}
                order.append(key)
            group = groups[key]
            group["variants"].append({
                "url": url,
                "label": self._variant_label(s),
                "bitrate": s.get("bitrate") or 0,
            })
            # Anzeigename der Gruppe: der (bereinigte) Name, der unter den
            # Rohtreffern am haeufigsten vorkommt, gewinnt - so zaehlen z.B.
            # drei "Deutschlandfunk | DLF | AAC ..."-Eintraege und ein
            # plaines "Deutschlandfunk" zusammen fuer denselben sauberen
            # Anzeigenamen "Deutschlandfunk", statt dass der haessliche
            # zusammengesetzte String gewinnt.
            display_name = self._display_name(name)
            group["name_counts"][display_name] = group["name_counts"].get(display_name, 0) + 1
            if not group["favicon"] and s.get("favicon"):
                group["favicon"] = s.get("favicon")

        results = []
        for key in order[:limit]:
            group = groups[key]
            group["variants"].sort(key=lambda v: v["bitrate"], reverse=True)
            canonical_name = max(group["name_counts"], key=group["name_counts"].get)
            results.append({
                "name": canonical_name,
                "favicon": group["favicon"],
                "country": group["country"],
                "url": group["variants"][0]["url"],  # beste Qualitaet als Standard
                "variants": group["variants"],
            })
        return results

    def play(self, url, name):
        self.player.play(url, title=name)
        self.player.set_volume(20)

    def pause(self):
        self.player.pause()

    def resume(self):
        self.player.resume()

    def stop(self):
        self.player.stop()

    # Kein next_track()/previous_track() - Web-Radio hat keine "naechste
    # Station", die Skip-Buttons im Frontend werden fuer diese Quelle
    # entsprechend deaktiviert (siehe app.js).

    def get_status(self):
        status = self.player.get_status()
        status["name"] = status.pop("title", None)
        return status
