# Spotty Radio – Systemdateien für den Raspberry Pi

Dieser Ordner enthält alle Einstellungen, die **außerhalb** des Projektordners
liegen. Die Pfade unter `deploy/pi/` entsprechen genau den Pfaden auf dem Pi
(`deploy/pi/etc/asound.conf` → `/etc/asound.conf`).

**Nicht** in Git (Zugangsdaten!) – diese Dateien kommen aus der Sicherung:
`.env`, `.spotify_cache`, `.librespot_cache/credentials.json`, außerdem das
selbst kompilierte `librespot` (0.8.0, liegt in `/usr/local/bin/librespot`).

| Datei | Zweck |
|---|---|
| `etc/systemd/system/spotify-radio.service` | startet die App beim Hochfahren |
| `etc/systemd/system/spotify-radio.service.d/unbuffered.conf` | Meldungen der App sofort ins Protokoll |
| `etc/systemd/system/spotify-radio-restart.service` + `.timer` | nächtlicher Neustart um 4 Uhr (nur wenn nichts läuft) |
| `usr/local/bin/spotify-radio-conditional-restart.sh` | Skript dazu |
| `etc/asound.conf` | Audio über HiFiBerry mit dmix (librespot + mpv gleichzeitig) |
| `etc/sudoers.d/010-lepoo-shutdown`, `020-lepoo-nmcli` | Herunterfahren/WLAN aus der App ohne Passwort |
| `etc/systemd/journald.conf.d/90-radio.conf` | Protokoll überlebt Neustarts, max. 50 MB |
| `etc/chromium/policies/managed/spotty-radio.json` | kein Übersetzungs-Popup |
| `home/lepoo/.config/labwc/autostart` | Display drehen, auf App warten, Chromium starten |
| `home/lepoo/.config/labwc/rc.xml`, `environment` | Touchscreen auf DSI-1, deutsches Tastaturlayout |
| `home/lepoo/.config/wf-panel-pi/wf-panel-pi.ini` | Taskleiste komplett ausblenden |
| `boot/firmware/config.txt` | nur zum Nachschlagen – **nicht** einfach kopieren, siehe unten |

## Neueinrichtung (z. B. nach Kartentausch)

1. **Raspberry Pi Imager:** Raspberry Pi OS (64-bit, mit Desktop), Benutzer
   `lepoo`, Hostname `Spotty-Radio`, WLAN und SSH einrichten.
2. **Pakete und Projekt:**
```bash
   sudo apt update && sudo apt full-upgrade -y
   sudo apt install -y git mpv python3-venv python3-dev gh
   git clone https://github.com/LePooGH/Spotify-Radio.git ~/Spotify-Radio
   cd ~/Spotify-Radio
   python3 -m venv --system-site-packages venv
   venv/bin/pip install -r requirements.txt
```
3. **Aus der Sicherung zurückspielen:** `.env`, `.spotify_cache`,
   `.librespot_cache/credentials.json` nach `~/Spotify-Radio/`, außerdem
   `sudo install -m 0755 librespot /usr/local/bin/librespot`.
4. **Systemdateien installieren:**
```bash
   cd ~/Spotify-Radio/deploy/pi
   for f in etc/systemd/system/spotify-radio.service \
            etc/systemd/system/spotify-radio.service.d/unbuffered.conf \
            etc/systemd/system/spotify-radio-restart.service \
            etc/systemd/system/spotify-radio-restart.timer \
            etc/asound.conf \
            etc/systemd/journald.conf.d/90-radio.conf \
            etc/chromium/policies/managed/spotty-radio.json; do
     sudo install -D -m 0644 "$f" "/$f"
   done
   sudo install -m 0755 usr/local/bin/spotify-radio-conditional-restart.sh /usr/local/bin/
   sudo install -m 0440 -o root -g root etc/sudoers.d/010-lepoo-shutdown etc/sudoers.d/020-lepoo-nmcli /etc/sudoers.d/
   sudo visudo -c
   mkdir -p ~/.config/labwc ~/.config/wf-panel-pi
   cp home/lepoo/.config/labwc/{autostart,rc.xml,environment} ~/.config/labwc/
   cp home/lepoo/.config/wf-panel-pi/wf-panel-pi.ini ~/.config/wf-panel-pi/
   sudo mkdir -p /var/log/journal
```
5. **config.txt anpassen** (die Datei selbst nicht kopieren, sie unterscheidet
   sich je nach OS-Version):
```bash
   sudo sed -i 's/^dtparam=audio=on/#dtparam=audio=on/; s/^dtoverlay=vc4-kms-v3d$/dtoverlay=vc4-kms-v3d,noaudio/' /boot/firmware/config.txt
   printf '\n[all]\ndtoverlay=hifiberry-dacplus-std\ndtoverlay=disable-bt\n' | sudo tee -a /boot/firmware/config.txt > /dev/null
```
   `cmdline.txt` **nie** von einer anderen Karte kopieren – sie enthält die
   Kennung der jeweiligen Karte, mit einer fremden startet der Pi nicht.
6. **WLAN-Stromsparmodus aus** (sonst ist das Radio zeitweise per SSH nicht
   erreichbar und librespot verliert die Verbindung):
```bash
   C=$(nmcli -t -f NAME,DEVICE connection show --active | grep ':wlan0$' | cut -d: -f1)
   sudo nmcli connection modify "$C" 802-11-wireless.powersave 2
```
7. **Dienste aktivieren und neu starten:**
```bash
   sudo systemctl daemon-reload
   sudo systemctl enable spotify-radio.service spotify-radio-restart.timer
   sudo reboot
```
8. **GitHub-Anmeldung** (zum Pushen vom Radio aus):
```bash
   git config --global user.name "Ole"
   git config --global user.email "ole.kilinc@hotmail.com"
   GH_BROWSER=false gh auth login --hostname github.com --git-protocol https --web
   gh auth setup-git
```

## Wichtige Hinweise

- Chromium **nicht** mit `--kiosk` starten – damit friert das gedrehte
  Display ein. Vollbild entsteht über die ausgeblendete Taskleiste.
- Die Dateien hier sind ein Abbild des laufenden Radios. Nach Änderungen an
  Systemdateien auf dem Pi diese Kopien mit aktualisieren und committen.
