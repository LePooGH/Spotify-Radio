"""
USB-MP3-Modul: Erkennt eingehaengte USB-Sticks, listet deren MP3-Inhalte auf
und spielt sie ueber den gemeinsamen MPVPlayer ab.

Erkennung: Linux haengt Wechseldatentraeger ueblicherweise automatisch unter
/media/<user>/<label> bzw. /run/media/<user>/<label> ein (via udisks2/gvfs).
Das gilt sowohl fuer den Ubuntu-Entwicklungslaptop (dort passiert das durch
die Desktop-Umgebung von selbst) als auch spaeter fuer den Pi, sobald dort
ein Automount eingerichtet ist. Dieses Modul mountet selbst nichts, es sucht
nur an diesen ueblichen Orten nach bereits eingehaengten Datentraegern mit
MP3-Inhalt.

Im Dev-Modus zaehlt zusaetzlich der lokale Testordner sample_usb als
"virtueller Stick", damit sich das Modul auch ohne echte Hardware testen
laesst.

Ist genau ein Stick mit MP3-Inhalt gefunden, wird er automatisch verwendet.
Sind es mehrere, muss der Nutzer im Interface auswaehlen (siehe set_device()) -
das Interface fragt dafuer zuerst list_devices() ab.
"""
import os
import re
import subprocess

try:
    from mutagen import File as MutagenFile
except ImportError:
    MutagenFile = None

AUDIO_EXTENSIONS = (".mp3", ".flac", ".ogg", ".wav", ".m4a")

# Zeichen, die in echten Song-/Hoerspiel-Titeln praktisch nie vorkommen, aber
# typisch fuer beschaedigte/fehlerhaft kodierte ID3-Tags sind (siehe
# Chat-Verlauf: Tags wie "T)dre" statt "Tiere", "End}ich" statt "Endlich").
# Taucht sowas auf, wird der Tag verworfen und stattdessen der - in diesem
# Fall meist sauberere - Dateiname verwendet.
_SUSPICIOUS_TAG_CHARS = set("\\`{}[]|~^\x00")

# Bekannte System-/Papierkorb-Ordner, die auf FAT32/exFAT-Sticks haeufig
# rumliegen (Windows-Papierkorb, macOS-Metadaten etc.) - werden beim
# Durchsuchen ignoriert, damit sie nicht als "Titel" auftauchen.
_IGNORED_DIR_NAMES = {
    "system volume information",
    "$recycle.bin",
    ".trashes",
    ".fseventsd",
    ".spotlight-v100",
    ".temporaryitems",
    "found.000",
}


class USBModule:
    def __init__(self, player, platform="dev", dev_folder="./sample_usb"):
        self.player = player
        self.platform = platform
        self.dev_folder = dev_folder
        self.selected_path = None
        # Merkt sich die Titelliste des Ordners, aus dem gerade abgespielt
        # wird, plus die aktuelle Position darin - noetig, damit
        # Weiter/Zurueck wissen, welcher Titel als naechstes dran ist.
        self._current_playlist = []
        self._current_index = 0
        self.current_path = None
        if platform == "dev":
            os.makedirs(dev_folder, exist_ok=True)

    def _candidate_roots(self):
        """Verzeichnisse, unter denen jeweils ein Unterordner pro
        eingehaengtem Datentraeger liegt."""
        roots = []
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        if user:
            for base in ("/media", "/run/media"):
                user_dir = os.path.join(base, user)
                if os.path.isdir(user_dir):
                    roots.append(user_dir)
        return roots

    def _prune_junk_dirs(self, dirnames):
        """Entfernt bekannte System-/Papierkorb-Ordner in-place, damit
        os.walk gar nicht erst hineinsteigt."""
        dirnames[:] = [
            d for d in dirnames
            if d.lower() not in _IGNORED_DIR_NAMES and not d.startswith(".")
        ]

    def _iter_audio_files(self, root):
        """Liefert (Dateipfad, Dateiname) fuer alle Audiodateien unterhalb
        von root - ueberspringt dabei System-/Papierkorb-Ordner sowie
        versteckte Dateien (z.B. macOS-Ressourcendateien wie '._Song.mp3',
        die automatisch entstehen, sobald der Stick mal an einem Mac war)."""
        for dirpath, dirnames, filenames in os.walk(root):
            self._prune_junk_dirs(dirnames)
            for fname in filenames:
                if fname.startswith("."):
                    continue
                if fname.lower().endswith(AUDIO_EXTENSIONS):
                    yield os.path.join(dirpath, fname), fname

    def _has_audio(self, path):
        for _ in self._iter_audio_files(path):
            return True
        return False

    def list_devices(self):
        """Findet alle eingehaengten Datentraeger mit MP3-Inhalt - das sind
        die zur Auswahl stehenden 'USB-Sticks'."""
        devices = []
        seen = set()

        if self.platform == "dev" and self._has_audio(self.dev_folder):
            devices.append({"name": "Test-Ordner (sample_usb)", "path": self.dev_folder})
            seen.add(os.path.realpath(self.dev_folder))

        for root in self._candidate_roots():
            try:
                entries = os.listdir(root)
            except OSError:
                continue
            for entry in entries:
                path = os.path.join(root, entry)
                real_path = os.path.realpath(path)
                if real_path in seen or not os.path.isdir(path):
                    continue
                if self._has_audio(path):
                    seen.add(real_path)
                    devices.append({"name": entry, "path": path})
        return devices

    def set_device(self, path):
        """Legt fest, welcher der gefundenen Sticks benutzt werden soll -
        relevant, wenn mehrere gleichzeitig eingesteckt sind."""
        self.selected_path = path

    def eject_device(self, path):
        """Haengt den angegebenen Stick sauber aus, bevor er physisch
        entfernt wird. Unser Modul schreibt zwar nie auf den Stick, aber
        sauberes Aushaengen schuetzt trotzdem vor zwei realen Problemen:
        laufende Wiedergabe (mpv haelt die Datei offen) und - vor allem bei
        FAT32/exFAT ohne Journal - Inkonsistenzen in der Dateizuordnungs-
        tabelle, falls das Betriebssystem beim Abziehen noch irgendeinen
        offenen Zugriff auf den Stick hatte.

        Nutzt `udisksctl unmount -b <Blockgeraet>`, das genau das macht,
        was auch ein Rechtsklick-"Auswerfen" im Dateimanager ausloesen
        wuerde - und ohne Sonderrechte funktioniert, solange der Stick (wie
        bei uns ueblich) vom aktuellen Nutzer selbst per udisks2
        eingehaengt wurde. Das zugehoerige Blockgeraet (z.B. /dev/sdb1) wird
        dafuer zuerst ueber `findmnt` aus dem Mount-Pfad ermittelt, da
        udisksctl selbst keinen normalen Dateisystem-Pfad akzeptiert."""
        # Laufende Wiedergabe stoppen, falls sie von diesem Stick kommt,
        # damit mpv die Datei sauber freigibt, bevor ausgehaengt wird.
        # (Pfadvergleich mit angehaengtem Trenner, damit z.B. "STICK" nicht
        # faelschlich als Praefix von "STICK2" erkannt wird.)
        stick_prefix = path.rstrip("/") + "/"
        if self.current_path and (self.current_path == path or self.current_path.startswith(stick_prefix)):
            self.stop()

        device = self._find_block_device_for_mount(path)
        if not device:
            return {"ok": False, "message": f"Kein Blockgeraet fuer '{path}' gefunden (findmnt lieferte nichts)."}

        try:
            result = subprocess.run(
                ["udisksctl", "unmount", "-b", device],
                capture_output=True, text=True, timeout=10,
            )
            success = result.returncode == 0
            message = (result.stdout or result.stderr or "").strip()
        except FileNotFoundError:
            success = False
            message = "udisksctl nicht gefunden - ist udisks2 installiert?"
        except (OSError, subprocess.TimeoutExpired) as exc:
            success = False
            message = str(exc)

        if success:
            if self.selected_path == path:
                self.selected_path = None
            # Zwischengespeicherte Kataloge/Titellisten dieses Sticks sind
            # nach dem Aushaengen hinfaellig.
            self._current_playlist = []
            self._current_index = 0
            self.current_path = None

        return {"ok": success, "message": message}

    def _find_block_device_for_mount(self, path):
        """Ermittelt das Blockgeraet (z.B. /dev/sdb1) fuer einen
        Mount-Pfad ueber `findmnt` - noetig, weil `udisksctl unmount` einen
        Blockgeraet-Pfad braucht, keinen normalen Dateisystem-Pfad."""
        try:
            result = subprocess.run(
                ["findmnt", "-n", "-o", "SOURCE", "--target", path],
                capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        device = result.stdout.strip()
        return device or None

    def _active_root(self):
        """Ermittelt den aktuell zu nutzenden Pfad: die explizite Auswahl,
        falls sie noch gueltig ist, sonst automatisch das einzige gefundene
        Geraet, sonst nichts (Auswahl noetig oder gar kein Stick da)."""
        devices = self.list_devices()
        if self.selected_path and any(d["path"] == self.selected_path for d in devices):
            return self.selected_path
        if len(devices) == 1:
            return devices[0]["path"]
        return None

    def _natural_sort_key(self, text):
        """Zerlegt einen Text in Ziffern-/Nicht-Ziffern-Abschnitte, damit
        z.B. 'Track 9' vor 'Track 10' einsortiert wird (reiner String-
        Vergleich wuerde '10' vor '9' einordnen)."""
        return [
            int(chunk) if chunk.isdigit() else chunk.lower()
            for chunk in re.split(r"(\d+)", text)
        ]

    def _device_display_name(self, root):
        """Ermittelt den Anzeigenamen des Sticks zu einem aufgeloesten Pfad -
        fuer den Fall, dass gar keine Unterordner existieren und der Bereich
        stattdessen den Namen des Sticks selbst tragen soll."""
        for d in self.list_devices():
            if d["path"] == root:
                return d["name"]
        return os.path.basename(root.rstrip("/")) or root

    def _is_within_active_root(self, path):
        """Sicherheitscheck: verhindert, dass ueber die Ordner-Endpunkte
        beliebige Pfade ausserhalb des aktiven Sticks gelesen werden."""
        root = self._active_root()
        if not root or not path:
            return False
        real_root = os.path.realpath(root)
        real_path = os.path.realpath(path)
        return real_path == real_root or real_path.startswith(real_root + os.sep)

    def list_tracks_in_folder(self, folder_path):
        """Listet die Audiodateien innerhalb eines bestimmten Ordners auf
        (nicht rekursiv ueber Geschwister-Ordner hinweg reduziert - falls der
        Ordner selbst wieder Unterordner enthaelt, werden die trotzdem mit
        erfasst, aber als ein gemeinsamer 'Alben'-Inhalt betrachtet)."""
        if not self._is_within_active_root(folder_path) or not os.path.isdir(folder_path):
            return []
        tracks = []
        for path, fname in self._iter_audio_files(folder_path):
            tags = self._read_tags(path, fname)
            tracks.append({"path": path, **tags})
        tracks.sort(key=lambda t: self._natural_sort_key(os.path.basename(t["path"])))
        return tracks

    def list_tracks(self):
        """Listet ALLE Audiodateien des aktiven Sticks auf, unabhaengig von
        der Ordnerstruktur (wird von der 'flat'/'single'-Ansicht in
        get_browse_info() sowie als generischer Endpunkt genutzt)."""
        root = self._active_root()
        if not root:
            return []
        return self.list_tracks_in_folder(root)

    def browse_path(self, path=None):
        """Liefert den Inhalt EINER Ordnerebene fuer einen echten
        Datei-Browser: direkte Unterordner (die irgendwo audio enthalten,
        auch verschachtelt) und direkte MP3-Dateien in genau diesem Ordner
        (nicht rekursiv). Damit laesst sich der Stick Ebene fuer Ebene
        durchklicken:

        - Ordner werden links in der Liste angezeigt, Klick geht eine
          Ebene tiefer
        - Liegen in der aktuellen Ebene direkte MP3-Dateien, erscheinen die
          rechts (unabhaengig davon, ob zusaetzlich noch Unterordner da sind)
        - "is_root"/"parent_path" erlauben eine "Zurueck"-Navigation"""
        root = self._active_root()
        if not root:
            return {"mode": "none"}
        if not path or not self._is_within_active_root(path) or not os.path.isdir(path):
            path = root

        device_name = self._device_display_name(root)

        subfolders = []
        files = []
        try:
            entries = sorted(os.listdir(path), key=self._natural_sort_key)
        except OSError:
            entries = []
        for entry in entries:
            if entry.startswith("."):
                continue
            entry_path = os.path.join(path, entry)
            if os.path.isdir(entry_path):
                if entry.lower() in _IGNORED_DIR_NAMES:
                    continue
                if self._has_audio(entry_path):
                    subfolders.append({"name": entry, "path": entry_path})
            elif entry.lower().endswith(AUDIO_EXTENSIONS):
                tags = self._read_tags(entry_path, entry)
                files.append({"path": entry_path, **tags})

        files.sort(key=lambda t: self._natural_sort_key(os.path.basename(t["path"])))

        is_root = os.path.realpath(path) == os.path.realpath(root)
        parent_path = None if is_root else os.path.dirname(path.rstrip("/"))
        current_name = device_name if is_root else os.path.basename(path.rstrip("/"))

        return {
            "mode": "browse",
            "device_name": device_name,
            "current_path": path,
            "current_name": current_name,
            "is_root": is_root,
            "parent_path": parent_path,
            "folders": subfolders,
            "files": files,
        }

    def play_folder(self, folder_path):
        """Spielt den ersten Titel eines Ordners (inkl. Unterordner) -
        Pendant zum Klick auf ein Spotify-Album-Cover, das ja ebenfalls die
        Wiedergabe direkt startet. Bewusst rekursiv (im Gegensatz zu
        browse_path), damit ein Klick auf eine Ordner-Ebene mit weiteren
        Unterordnern trotzdem sofort etwas abspielt."""
        tracks = self.list_tracks_in_folder(folder_path)
        if tracks:
            self.play(tracks[0]["path"])

    def _clean_fallback_title(self, filename):
        """Erzeugt einen lesbaren Titel aus dem Dateinamen, falls keine (oder
        keine brauchbaren) ID3-Tags vorhanden sind: Dateiendung weg,
        Unterstriche durch Leerzeichen ersetzt, doppelte Leerzeichen weg."""
        name = os.path.splitext(filename)[0]
        name = name.replace("_", " ")
        return " ".join(name.split())

    def _looks_corrupted(self, text):
        """Einfache Heuristik gegen beschaedigte/fehlerhaft kodierte
        ID3-Tags: enthaelt der Text Zeichen, die in echten Titeln praktisch
        nie vorkommen (Rueckwaertsschraegstrich, Backtick, geschweifte
        Klammern etc.), wird er verworfen."""
        return any(ch in _SUSPICIOUS_TAG_CHARS for ch in text)

    def _read_tags(self, path, fallback_name):
        fallback_title = self._clean_fallback_title(fallback_name)
        if MutagenFile is None:
            return {"title": fallback_title, "artist": None}
        try:
            audio = MutagenFile(path, easy=True)
            if not audio:
                return {"title": fallback_title, "artist": None}

            tag_title = audio.get("title", [None])[0]
            if tag_title and not self._looks_corrupted(tag_title):
                title = tag_title
            else:
                title = fallback_title

            tag_artist = audio.get("artist", [None])[0]
            artist = tag_artist if tag_artist and not self._looks_corrupted(tag_artist) else None

            return {"title": title, "artist": artist}
        except Exception:
            return {"title": fallback_title, "artist": None}

    def play(self, path):
        # Kontext merken: die Titelliste des Ordners, in dem diese Datei
        # liegt, plus die Position darin - das ist die Grundlage fuer
        # Weiter/Zurueck (siehe next_track/previous_track).
        folder = os.path.dirname(path)
        self._current_playlist = self.list_tracks_in_folder(folder)
        self._current_index = next(
            (i for i, t in enumerate(self._current_playlist) if t["path"] == path),
            0,
        )
        self.current_path = path
        self.player.play(path, title=os.path.basename(path))

    def pause(self):
        self.player.pause()

    def resume(self):
        # Wurde noch gar kein Titel ausgewaehlt (z.B. direkt nach dem
        # Einstecken des Sticks), soll der Play-Button automatisch den
        # ersten Titel starten, statt dass man zwingend erst manuell einen
        # in der Liste anklicken muss.
        if not self._current_playlist:
            self._auto_start_first_track()
            return
        self.player.resume()

    def _auto_start_first_track(self):
        """Ermittelt den ersten sinnvollen Titel (je nach Ordnerstruktur:
        der Ordner selbst, oder bei mehreren Ordnern der erste davon) und
        startet ihn."""
        info = self.get_browse_info()
        tracks = None
        if info.get("mode") in ("single", "flat"):
            tracks = info.get("tracks")
        elif info.get("mode") == "multi":
            folders = info.get("folders") or []
            if folders:
                tracks = self.list_tracks_in_folder(folders[0]["path"])
        if tracks:
            self.play(tracks[0]["path"])

    def stop(self):
        self.player.stop()

    def next_track(self):
        if not self._current_playlist:
            return
        self._current_index = (self._current_index + 1) % len(self._current_playlist)
        self._play_current_index()

    def previous_track(self):
        if not self._current_playlist:
            return
        self._current_index = (self._current_index - 1) % len(self._current_playlist)
        self._play_current_index()

    def _play_current_index(self):
        track = self._current_playlist[self._current_index]
        self.current_path = track["path"]
        self.player.play(track["path"], title=os.path.basename(track["path"]))

    def get_status(self):
        status = self.player.get_status()
        status["name"] = status.pop("title", None)
        status["path"] = self.current_path
        return status
