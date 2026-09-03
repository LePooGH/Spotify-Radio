"""
Generischer Player fuer Web-Radio-Streams und lokale Audiodateien.

Steuert mpv ueber dessen IPC-Socket (JSON-Protokoll). Das funktioniert
identisch auf dem Ubuntu-Entwicklungslaptop und spaeter auf dem Raspberry Pi -
einzige Voraussetzung ist das mpv-Kommandozeilenprogramm (apt install mpv).
"""
import json
import os
import re
import socket
import subprocess
import time


class MPVPlayer:
    def __init__(self, socket_path="/tmp/radio-mpv.sock"):
        self.socket_path = socket_path
        self._process = None
        self.current_title = None

    def _ensure_running(self):
        if self._process is not None and self._process.poll() is None:
            return
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)
        self._process = subprocess.Popen(
            [
                "mpv",
                "--no-video",
                "--idle=yes",
                "--ao=alsa", "--audio-device=alsa",
                f"--input-ipc-server={self.socket_path}",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Kurz warten, bis mpv den Socket angelegt hat
        for _ in range(30):
            if os.path.exists(self.socket_path):
                return
            time.sleep(0.1)
        raise RuntimeError(
            "mpv-Socket wurde nicht erstellt - ist mpv installiert? "
            "(sudo apt install mpv)"
        )

    def _send(self, command):
        self._ensure_running()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect(self.socket_path)
                s.sendall((json.dumps({"command": command}) + "\n").encode())
                raw = s.recv(4096).decode()
                return json.loads(raw.splitlines()[0]) if raw else None
        except (OSError, json.JSONDecodeError):
            return None

    def play(self, url_or_path, title=None):
        self._send(["loadfile", url_or_path, "replace"])
        self._send(["set_property", "pause", False])
        self.current_title = title or url_or_path

    def pause(self):
        self._send(["set_property", "pause", True])

    def resume(self):
        self._send(["set_property", "pause", False])

    def stop(self):
        # Nur tatsaechlich stoppen, wenn mpv ueberhaupt laeuft - sonst wuerde
        # _send() unnoetig einen neuen mpv-Prozess starten, nur um ihm
        # "stop" zu sagen, obwohl gar nichts spielt.
        if self._process is not None and self._process.poll() is None:
            self._send(["stop"])
        self.current_title = None

    def set_volume(self, level):
        self._send(["set_property", "volume", int(level)])

    def get_status(self):
        pause_result = self._send(["get_property", "pause"])
        volume_result = self._send(["get_property", "volume"])
        is_playing = bool(pause_result) and pause_result.get("data") is False
        return {
            "active": self.current_title is not None,
            "is_playing": is_playing,
            "title": self.current_title,
            "song_title": self._get_song_title(),
            "volume_percent": (volume_result or {}).get("data"),
        }

    # Schluessel, unter denen mpv das aktuell gesendete ICY-"StreamTitle"
    # (meistens "Interpret - Songtitel") ablegt - variiert je nach
    # mpv-Version/Stream-Typ, deshalb werden mehrere Varianten probiert.
    _ICY_TITLE_KEYS = ("icy-title", "icy-title-1", "title", "StreamTitle")

    def _get_song_title(self):
        """Liest den aktuell vom Stream gesendeten Songtitel aus den
        ICY-Metadaten aus (funktioniert nur bei Sendern, die das ueberhaupt
        mitsenden - viele tun das, aber nicht alle). Gibt None zurueck, wenn
        nichts verfuegbar ist, statt einen Fehler zu werfen."""
        result = self._send(["get_property", "metadata"])
        meta = (result or {}).get("data")
        if not isinstance(meta, dict):
            return None
        # Case-insensitiver Abgleich, da mpv die Gross-/Kleinschreibung der
        # Metadaten-Keys je nach Stream unterschiedlich durchreicht.
        lowered = {k.lower(): v for k, v in meta.items()}
        for key in self._ICY_TITLE_KEYS:
            value = lowered.get(key.lower())
            if value:
                return self._clean_song_title(value)
        return None

    # Bekannte Muster, die Sender gerne VOR den eigentlichen Songtitel packen
    # und die sich einigermassen zuverlaessig erkennen lassen (im Gegensatz
    # zu freiem Fliesstext wie Ticker-Meldungen, der sich nicht generisch
    # von einem Interpretennamen unterscheiden laesst).
    _HOTLINE_RE = re.compile(r"\bhotline\b[\d\s]*", re.IGNORECASE)
    _SCORE_RE = re.compile(r"\b\d+\s*(zu|:)\s*\d+\b", re.IGNORECASE)

    def _clean_song_title(self, raw_title):
        """Manche Sender packen Werbetext/Hotline-Nummern/Ticker-Infos (z.B.
        Sportergebnisse) mit in dasselbe Metadaten-Feld wie den eigentlichen
        Songtitel, ohne sauber getrennte Felder - z.B. 'Hotline 0421...
        WM2026 Deutschland 2 zu 1 Spanien Ed Sheeran - Perfect'. Es gibt
        dafuer kein einheitliches Format, deshalb nur eine Heuristik:

        1. Bekannte, halbwegs zuverlaessig erkennbare Muster (Hotline-
           Nummern, Ticker-Zahlen wie "2 zu 1") werden gezielt entfernt.
        2. Der Songtitel folgt so gut wie immer dem Muster 'Interpret -
           Titel' - Aufteilung am LETZTEN ' - ' (die echten Songinfos
           stehen meist ganz am Ende).
        3. Beim Interpreten-Teil werden nur die letzten 3 Woerter behalten,
           falls davor noch Text uebrig ist (deckt die meisten Interpreten-
           namen ab, kann aber bei sehr langen Bandnamen zu kurz greifen).

        Das ist ein Best-Effort-Ansatz, kein Garant fuer 100% saubere
        Ergebnisse bei jedem Sender - freier Ticker-Text laesst sich
        generisch nicht zuverlaessig von einem Interpretennamen
        unterscheiden. Falls es bei einem bestimmten Sender weiterhin
        hakt, kann fuer dessen exaktes Format gezielt nachgebessert werden."""
        text = (raw_title or "").strip()
        text = self._HOTLINE_RE.sub(" ", text)
        text = self._SCORE_RE.sub(" ", text)
        text = " ".join(text.split())
        if " - " not in text:
            return text or None
        before, _, after = text.rpartition(" - ")
        before_words = before.split()
        if len(before_words) > 3:
            before = " ".join(before_words[-3:])
        cleaned = f"{before.strip()} - {after.strip()}".strip(" -")
        return cleaned or None
