"""
Zeitplan-Modul: taeglicher Aus-/Aufwach-Zeitpunkt (reine Software-Pause,
kein echtes Herunterfahren - siehe Chat-Verlauf, GPIO3 ist fuer ein
Hardware-Aufwecken wegen I2C-Konflikt mit dem Amp2 nicht nutzbar) sowie
ein einmaliger Einschlaf-Timer, der nach Ablauf tatsaechlich herunterfaehrt.

Persistiert Aus-/Aufwach-Zeit in einer JSON-Datei, damit sie App-Neustarts
uebersteht. Der Einschlaf-Timer wird bewusst NICHT persistiert - er ist
eine einmalige, laufzeitgebundene Aktion, nach einem Neustart waere ein
"Rest-Timer" ohnehin bedeutungslos.

Dev-Modus: Weder Zeitplan-Ueberwachung noch Displaybeleuchtung werden
angefasst (kein Backlight-Sysfs auf dem Laptop vorhanden).
"""
import glob
import json
import os
import subprocess
import threading
import time
from datetime import datetime

# Der Name des Backlight-Geraets haengt vom Display/Kernel ab - deshalb
# wird der erste vorhandene bl_power-Knoten genommen statt eines festen
# Pfads (06.11.2026: Standby-Modus).
_BACKLIGHT_CANDIDATES = sorted(glob.glob("/sys/class/backlight/*/bl_power"))
BACKLIGHT_PATH = _BACKLIGHT_CANDIDATES[0] if _BACKLIGHT_CANDIDATES else "/sys/class/backlight/panel_backlight@1/bl_power"


class Scheduler:
    def __init__(self, config_path, on_off_action, on_wake_action, platform="dev"):
        self.config_path = config_path
        self.on_off_action = on_off_action    # Callback: Wiedergabe stoppen
        self.on_wake_action = on_wake_action  # Callback: zuletzt gespielten Titel starten
        self.platform = platform
        self._lock = threading.Lock()
        self._sleep_timer = None
        self._sleep_timer_started_at = None
        self._sleep_timer_minutes = None
        self._last_triggered_minute = None
        self.off_time = None
        self.on_time = None
        # Standby: Display aus, Wiedergabe gestoppt - wird per Zeitplan
        # (Aus-Zeit), ueber den Aus-/Neustart-Dialog oder einen Einschlaf-
        # Timer betreten und per Zeitplan (Aufwach-Zeit) oder Beruehrung
        # des Displays wieder verlassen (siehe Chat-Verlauf 12.11.2026).
        self.standby = False
        self._load()
        # Nach einem App-Neustart ist der Standby-Zustand vergessen - die
        # Beleuchtung aber evtl. noch aus (12.11.2026: dunkles Display, das
        # auf Beruehrung reagierte). Deshalb beim Start immer einschalten.
        self._set_backlight(True)
        if platform == "pi":
            threading.Thread(target=self._watch_loop, daemon=True).start()
        else:
            print("[Scheduler] Dev-Modus: keine Zeitplan-Ueberwachung, kein Backlight.")

    # --- Persistenz ----------------------------------------------------------

    def _load(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.off_time = data.get("off_time")
            self.on_time = data.get("on_time")
        except (OSError, json.JSONDecodeError):
            pass

    def _save(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump({"off_time": self.off_time, "on_time": self.on_time}, f)
        except OSError:
            pass

    def get_schedule(self):
        return {
            "off_time": self.off_time,
            "on_time": self.on_time,
        }

    def set_schedule(self, off_time=None, on_time=None, clear_off=False, clear_on=False):
        with self._lock:
            if clear_off:
                self.off_time = None
            elif off_time:
                self.off_time = off_time
            if clear_on:
                self.on_time = None
            elif on_time:
                self.on_time = on_time
            self._save()

    # --- Displaybeleuchtung ----------------------------------------------------

    def _set_backlight(self, on):
        if self.platform != "pi":
            return
        try:
            with open(BACKLIGHT_PATH, "w") as f:
                f.write("0" if on else "1")
        except OSError as exc:
            print(f"[Scheduler] Backlight konnte nicht geschaltet werden: {exc}")

    # --- Taegliche Ueberwachung ------------------------------------------------

    def _watch_loop(self):
        while True:
            now = datetime.now().strftime("%H:%M")
            if now != self._last_triggered_minute:
                self._last_triggered_minute = now
                if self.off_time and now == self.off_time:
                    print("[Scheduler] Aus-Zeit erreicht - Standby.")
                    self.enter_standby()
                if self.on_time and now == self.on_time:
                    print("[Scheduler] Aufwach-Zeit erreicht - setze Wiedergabe fort.")
                    self.wake(resume=True)
            time.sleep(15)

    # --- Standby ---------------------------------------------------------------

    def enter_standby(self):
        """Display aus und Wiedergabe stoppen. Mehrfaches Aufrufen ist
        unschaedlich."""
        self.standby = True
        self._set_backlight(False)
        self._safe_call(self.on_off_action)

    def wake(self, resume=False):
        """Display wieder an. resume=True (Aufwach-Zeit) setzt zusaetzlich
        die letzte Wiedergabe fort; bei einer Beruehrung des Displays
        (resume=False) bleibt es still, bis jemand Play drueckt."""
        was_standby = self.standby
        self.standby = False
        self._set_backlight(True)
        if resume:
            self._safe_call(self.on_wake_action)
        return was_standby

    @staticmethod
    def _safe_call(fn):
        try:
            fn()
        except Exception as exc:
            print(f"[Scheduler] Aktion fehlgeschlagen: {exc}")

    # --- Einschlaf-Timer (echtes Herunterfahren) --------------------------------

    def start_sleep_timer(self, minutes):
        with self._lock:
            self._cancel_sleep_timer_locked()
            self._sleep_timer = threading.Timer(minutes * 60, self._trigger_shutdown)
            self._sleep_timer.daemon = True
            self._sleep_timer.start()
            self._sleep_timer_started_at = time.time()
            self._sleep_timer_minutes = minutes

    def cancel_sleep_timer(self):
        with self._lock:
            self._cancel_sleep_timer_locked()

    def _cancel_sleep_timer_locked(self):
        if self._sleep_timer is not None:
            self._sleep_timer.cancel()
        self._sleep_timer = None
        self._sleep_timer_started_at = None
        self._sleep_timer_minutes = None

    def get_sleep_timer_remaining(self):
        with self._lock:
            if self._sleep_timer is None or self._sleep_timer_started_at is None:
                return None
            elapsed = time.time() - self._sleep_timer_started_at
            remaining = self._sleep_timer_minutes * 60 - elapsed
            return max(0, int(remaining))

    def _trigger_shutdown(self):
        print("[Scheduler] Einschlaf-Timer abgelaufen - fahre Pi herunter...")
        try:
            subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
            print(f"[Scheduler] Herunterfahren fehlgeschlagen: {exc}")
