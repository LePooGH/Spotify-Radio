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
import threading
import time


class SpotifyConnectDaemon:
    def __init__(self, device_name="Spotty Radio", backend="pulseaudio",
                 cache_dir=".librespot_cache", initial_volume=70, binary_name="librespot",
                 audio_device=None):
        self.device_name = device_name
        self.backend = backend
        self.cache_dir = cache_dir
        self.initial_volume = initial_volume
        self.binary_name = binary_name
        # Konkretes ALSA-Geraet (z.B. "plughw:2,0") statt "default" - auf
        # manchen Systemen (z.B. mit PipeWire, aber ohne aktive grafische
        # Sitzung) findet librespot "default" nicht zuverlaessig, obwohl
        # das Geraet selbst einwandfrei funktioniert (siehe Chat-Verlauf).
        # None/leer = librespot nutzt weiterhin sein eigenes "default".
        self.audio_device = audio_device
        self._process = None
        self._unavailable = False  # librespot fehlt - nicht bei jedem start() erneut versuchen/loggen

    def start(self):
        """Startet librespot im Hintergrund, falls es nicht schon laeuft.
        Gibt bewusst KEINEN Fehler nach aussen weiter, wenn librespot fehlt
        oder nicht startet - die App soll trotzdem ganz normal weiterlaufen
        (dann eben mit einem externen Connect-Geraet wie bisher). Prueft
        aber aktiv, ob der Prozess kurz nach dem Start noch laeuft, statt
        blind "erfolgreich gestartet" zu melden - sonst bleibt ein
        sofortiger Absturz (z.B. durch ein falsches --backend) unbemerkt im
        Hintergrund, waehrend die App faelschlich Erfolg meldet (siehe
        Chat-Verlauf: genau das ist zwischenzeitlich durch einen
        Umgebungs-Reset wieder verloren gegangen und hat erneut fuer
        Verwirrung gesorgt)."""
        if self._unavailable:
            return
        if self._process is not None and self._process.poll() is None:
            return  # laeuft schon

        os.makedirs(self.cache_dir, exist_ok=True)
        args = [
            self.binary_name,
            "--name", self.device_name,
            "--backend", self.backend,
            "--cache", self.cache_dir,
            "--initial-volume", str(self.initial_volume),
            "--bitrate", "320",
        ]
        if self.audio_device:
            args += ["--device", self.audio_device]
        try:
            self._process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except FileNotFoundError:
            self._unavailable = True
            print(
                f"[Spotify-Connect] '{self.binary_name}' wurde nicht gefunden - "
                "Spotify-Wiedergabe erfordert bis zur Installation weiterhin "
                "ein externes Connect-Geraet (Handy/Spotify-App). "
                "Installationshinweise siehe README."
            )
            return

        # Kurz warten und pruefen, ob der Prozess sofort wieder abgestuerzt
        # ist (z.B. wegen eines nicht unterstuetzten --backend-Werts) -
        # solche Startfehler passieren typischerweise innerhalb der ersten
        # ein bis zwei Sekunden.
        time.sleep(1.5)
        if self._process.poll() is not None:
            output = self._process.stdout.read() if self._process.stdout else ""
            print(
                f"[Spotify-Connect] '{self.binary_name}' ist direkt nach dem "
                f"Start abgestuerzt (Exit-Code {self._process.returncode}). "
                f"Spotify-Wiedergabe erfordert bis zur Behebung weiterhin ein "
                f"externes Connect-Geraet. Fehlerausgabe:\n{output.strip()}"
            )
            self._process = None
            return

        print(
            f"[Spotify-Connect] {self.binary_name} laeuft als Geraet "
            f"'{self.device_name}' (Backend: {self.backend}). Falls "
            f"das Geraet noch nie verbunden wurde, einmalig in der "
            f"Spotify-App aus der Connect-Geraeteliste auswaehlen."
        )
        # Ab jetzt laeuft der Prozess dauerhaft im Hintergrund weiter - die
        # Ausgabe muss kontinuierlich abgeholt (und hier bewusst verworfen)
        # werden, sonst koennte der interne Puffer irgendwann volllaufen und
        # librespot beim Schreiben blockieren.
        threading.Thread(target=self._drain_output, daemon=True).start()

    def _drain_output(self):
        process = self._process
        if not process or not process.stdout:
            return
        try:
            for _ in process.stdout:
                pass
        except (OSError, ValueError):
            pass

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
