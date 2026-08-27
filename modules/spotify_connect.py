"""
Spotify-Connect-Daemon: startet und verwaltet einen eigenen `librespot`-
Hintergrundprozess, damit die Radio-App SELBST als Spotify-Connect-Ziel
erscheint - ohne dass man zusaetzlich Spotify auf dem Handy/Laptop offen
haben muss. Funktioniert nach demselben Prinzip wie unser MPVPlayer fuer
Web-Radio/USB: ein von uns selbst gestarteter und verwalteter Hintergrund-
prozess statt eines externen Programms, das man manuell offen halten muss.

Einmaliges Setup (danach nie wieder noetig):
1. librespot installieren (z.B. `cargo install librespot` - siehe README)
2. Radio-App einmal starten, damit dieser Daemon librespot im Hintergrund
   hochfaehrt
3. Auf dem Handy/Desktop EINMAL in der Spotify-App das neue Geraet (Name
   siehe SPOTIFY_DEVICE_NAME) aus der Connect-Geraeteliste auswaehlen -
   das ist der sogenannte Zeroconf-Kopplungsvorgang, wie beim erstmaligen
   Einrichten eines neuen smarten Lautsprechers
4. Ab jetzt merkt sich librespot die Anmeldedaten dauerhaft im Cache-Ordner
   und meldet sich bei jedem weiteren App-Start automatisch wieder an -
   die Spotify-App muss dafuer nicht mehr geoeffnet werden

Ohne uebergebenen Benutzername/Passwort aktiviert librespot automatisch den
Zeroconf-Discovery-Modus (das ist der oben beschriebene Kopplungsvorgang) -
Passwort-Login wurde von Spotify inzwischen ohnehin abgeschaltet.
"""
import os
import subprocess


class SpotifyConnectDaemon:
    def __init__(self, device_name="Spotty Radio", backend="pulseaudio",
                 cache_dir=".librespot_cache", initial_volume=70, binary_name="librespot"):
        self.device_name = device_name
        self.backend = backend
        self.cache_dir = cache_dir
        self.initial_volume = initial_volume
        self.binary_name = binary_name
        self._process = None
        self._unavailable = False  # librespot fehlt - nicht bei jedem start() erneut versuchen/loggen

    def start(self):
        """Startet librespot im Hintergrund, falls es nicht schon laeuft.
        Gibt bewusst KEINEN Fehler nach aussen weiter, wenn librespot fehlt
        oder nicht startet - die App soll trotzdem ganz normal weiterlaufen
        (dann eben mit einem externen Connect-Geraet wie bisher)."""
        if self._unavailable:
            return
        if self._process is not None and self._process.poll() is None:
            return  # laeuft schon

        os.makedirs(self.cache_dir, exist_ok=True)
        try:
            self._process = subprocess.Popen(
                [
                    self.binary_name,
                    "--name", self.device_name,
                    "--backend", self.backend,
                    "--cache", self.cache_dir,
                    "--initial-volume", str(self.initial_volume),
                    "--bitrate", "320",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(
                f"[Spotify-Connect] {self.binary_name} gestartet als Geraet "
                f"'{self.device_name}' (Backend: {self.backend}). Falls "
                f"das Geraet noch nie verbunden wurde, einmalig in der "
                f"Spotify-App aus der Connect-Geraeteliste auswaehlen."
            )
        except FileNotFoundError:
            self._unavailable = True
            print(
                f"[Spotify-Connect] '{self.binary_name}' wurde nicht gefunden - "
                "Spotify-Wiedergabe erfordert bis zur Installation weiterhin "
                "ein externes Connect-Geraet (Handy/Spotify-App). "
                "Installationshinweise siehe README."
            )

    def stop(self):
        """Beendet librespot sauber - wird beim Herunterfahren der App
        aufgerufen (siehe atexit-Registrierung in app.py)."""
        if self._process is not None and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None

    def is_running(self):
        return self._process is not None and self._process.poll() is None
