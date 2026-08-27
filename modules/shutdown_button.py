"""
GPIO-Aus-Knopf: faehrt den Pi sauber herunter, statt dass man einfach den
Stecker zieht - schuetzt die SD-Karte vor Beschaedigung durch abrupten
Stromverlust (siehe Chat-Verlauf).

Dev-Modus (Ubuntu-Laptop): Es ist keine Hardware vorhanden - diese Klasse
tut dann nichts, ausser eine Meldung auszugeben (gleiches Prinzip wie
InputController fuer den Drehencoder).

Pi-Modus: Ueberwacht einen GPIO-Pin per gpiozero. Ein LANGER Tastendruck
(mehrere Sekunden gehalten, nicht nur kurz beruehrt) loest das
Herunterfahren aus - eine versehentliche kurze Beruehrung reicht bewusst
NICHT aus, damit man den Pi nicht aus Versehen mitten im Hoeren
herunterfaehrt.

WICHTIGE EINMALIGE EINRICHTUNG AUF DEM PI (siehe auch README): Damit
`sudo shutdown` ohne Passwort-Abfrage funktioniert (noetig, da dieses
Skript nicht interaktiv laeuft), muss einmalig eine sudoers-Regel
eingerichtet werden - siehe README fuer die genauen Befehle. Ohne das
schlaegt das Herunterfahren fehl (Passwort-Prompt haengt im Hintergrund).
"""
import subprocess


class ShutdownButton:
    def __init__(self, platform, pin=26, hold_seconds=3, enabled=True):
        self.platform = platform
        self.pin = pin
        self.hold_seconds = hold_seconds
        self.enabled = enabled
        self._button = None

        if platform != "pi":
            print(
                "[ShutdownButton] Dev-Modus: kein Aus-Knopf angeschlossen - "
                "zum Beenden reicht Strg+C im Terminal."
            )
            return
        if not enabled:
            print(
                "[ShutdownButton] Deaktiviert (SHUTDOWN_BUTTON_ENABLED=false) "
                "- kein Knopf angeschlossen? Verhindert falsche Ausloeser "
                "durch einen frei schwebenden, nicht verbundenen GPIO-Pin."
            )
            return
        self._init_gpio()

    def _init_gpio(self):
        from gpiozero import Button

        self._button = Button(self.pin, hold_time=self.hold_seconds)
        self._button.when_held = self._handle_shutdown
        print(
            f"[ShutdownButton] Aus-Knopf an GPIO{self.pin} aktiv - "
            f"{self.hold_seconds} Sekunden gedrueckt halten zum sauberen "
            f"Herunterfahren."
        )

    def _handle_shutdown(self):
        print("[ShutdownButton] Aus-Knopf gehalten - fahre Pi sauber herunter...")
        try:
            subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
            print(
                f"[ShutdownButton] Herunterfahren fehlgeschlagen: {exc}. "
                "Ist die passwortlose sudoers-Regel eingerichtet (siehe README)?"
            )
