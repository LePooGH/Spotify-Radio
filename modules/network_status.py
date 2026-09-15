"""
WLAN-Status und -Verwaltung ueber nmcli. Ermoeglicht der Weboberflaeche,
den Verbindungsstatus anzuzeigen und sich bei Bedarf direkt ueber das
Touchdisplay neu einzuloggen, ohne Tastatur/Maus am Pi anschliessen zu
muessen (siehe Chat-Verlauf: am 15.09.2026 war das gespeicherte WLAN-
Profil komplett verschwunden, Diagnose ging nur ueber eine angeschlossene
USB-Tastatur - dieser Button soll das kuenftig direkt am Radio loesen).
"""
import subprocess


def get_status():
    try:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "DEVICE,STATE,CONNECTION", "device", "status"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[0] == "wlan0":
                connected = parts[1] == "connected"
                ssid = parts[2] if connected else None
                return {"connected": connected, "ssid": ssid}
        return {"connected": False, "ssid": None}
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {"connected": False, "ssid": None, "error": "Status konnte nicht ermittelt werden"}


def scan_networks():
    try:
        subprocess.run(["sudo", "nmcli", "device", "wifi", "rescan"], capture_output=True, timeout=10)
        result = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL", "device", "wifi", "list"],
            capture_output=True, text=True, timeout=10,
        )
        seen = set()
        networks = []
        for line in result.stdout.splitlines():
            parts = line.rsplit(":", 1)
            if len(parts) != 2:
                continue
            ssid, signal = parts
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            try:
                signal_val = int(signal)
            except ValueError:
                signal_val = 0
            networks.append({"ssid": ssid, "signal": signal_val})
        networks.sort(key=lambda n: -n["signal"])
        return networks
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []


def connect(ssid, password):
    try:
        result = subprocess.run(
            ["sudo", "nmcli", "device", "wifi", "connect", ssid, "password", password],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode == 0:
            return {"ok": True}
        return {"ok": False, "error": result.stderr.strip() or result.stdout.strip()}
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        return {"ok": False, "error": str(exc)}
