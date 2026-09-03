"""
GPIO-Ein-/Ausschalter: faehrt den Pi sauber herunter, statt dass man
einfach den Stecker zieht - schuetzt die SD-Karte vor Beschaedigung durch
abrupten Stromverlust (siehe Chat-Verlauf).

Dev-Modus (Ubuntu-Laptop): Es ist keine Hardware vorhanden - diese Klasse
tut dann nichts, ausser eine Meldung auszugeben.

Pi-Modus: Ueberwacht einen GPIO-Pin per gpiozero. Steht der Schalter auf
"aus" (Stromkreis offen, Pin liest HIGH), startet ein Timer - bleibt er
laenger als hold_seconds in dieser Stellung, wird sauber heruntergefahren.
Wird rechtzeitig zurueck auf "ein" gelegt, wird der Timer abgebrochen -
ein kurzes versehentliches Umlegen loest also NICHT sofort ein
Herunterfahren aus.

WICHTIGE EINMALIGE EINRICHTUNG AUF DEM PI (siehe auch README): Damit
`sudo shutdown` ohne Passwort-Abfrage funktioniert, muss einmalig eine
sudoers-Regel eingerichtet werden - siehe README.
"""
import subprocess
import threading


class ShutdownButton:
    def __init__(self, platform, pin=26, hold_seconds=3, enabled=True):
        self.platform = platform
        self.pin = pin
        self.hold_seconds = hold_seconds
        self.enabled = enabled
        self._button = None
        self._timer = None

        if platform != "pi":
            print(
                "[ShutdownButton] Dev-Modus: kein Schalter angeschlossen - "
                "zum Beenden reicht Strg+C im Terminal."
            )
            return
        if not enabled:
            print(
                "[ShutdownButton] Deaktiviert (SHUTDOWN_BUTTON_ENABLED=false) "
                "- kein Schalter angeschlossen? Verhindert falsche Ausloeser "
                "durch einen frei schwebenden, nicht verbundenen GPIO-Pin."
            )
            return
        self._init_gpio()

    def _init_gpio(self):
        from gpiozero import Button

        self._button = Button(self.pin)
        self._button.when_released = self._start_shutdown_timer
        self._button.when_pressed = self._cancel_shutdown_timer
        print(
            f"[ShutdownButton] Ein-/Ausschalter an GPIO{self.pin} aktiv - "
            f"Schalter {self.hold_seconds} Sekunden auf 'aus' lassen zum "
            f"sauberen Herunterfahren."
        )

    def _start_shutdown_timer(self):
        self._timer = threading.Timer(self.hold_seconds, self._handle_shutdown)
        self._timer.start()

    def _cancel_shutdown_timer(self):
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _handle_shutdown(self):
        print("[ShutdownButton] Schalter auf 'aus' - fahre Pi sauber herunter...")
        try:
            subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
            print(
                f"[ShutdownButton] Herunterfahren fehlgeschlagen: {exc}. "
                "Ist die passwortlose sudoers-Regel eingerichtet (siehe README)?"
            )
