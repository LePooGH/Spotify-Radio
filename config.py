"""
Zentrale Konfiguration.

PLATFORM steuert, welche Hardware-Implementierung geladen wird:
  - "dev": Ubuntu-Laptop, keine echte Hardware vorhanden
  - "pi":  Raspberry Pi mit Amp2, Touchdisplay und Drehencoder

Alle Werte lassen sich über eine .env-Datei überschreiben (siehe .env.example).
"""
import os
from dotenv import load_dotenv

load_dotenv()

PLATFORM = os.getenv("PLATFORM", "dev")  # "dev" oder "pi"

# Branch, von dem das Selbst-Update (siehe modules/updater.py) die neueste
# Version zieht.
UPDATE_BRANCH = os.getenv("UPDATE_BRANCH", "main")

# --- Spotify --------------------------------------------------------------
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:5000/callback")
# Name des Spotify-Connect-Zielgeräts. Wird sowohl als Name fürs
# selbstverwaltete librespot (siehe SPOTIFY_CONNECT_ENABLED) als auch als
# Erkennungs-Heuristik genutzt, falls stattdessen ein externes Gerät (Handy
# mit offener Spotify-App, raspotify o.ä.) verwendet wird.
SPOTIFY_DEVICE_NAME = os.getenv("SPOTIFY_DEVICE_NAME", "Spotty Radio")

# Startet automatisch einen eigenen librespot-Hintergrundprozess, damit die
# Radio-App selbst als Spotify-Connect-Ziel erscheint - keine separate
# Spotify-App muss mehr offen sein. Erfordert eine einmalige Kopplung ueber
# die Spotify-App (siehe README) und das librespot-Programm auf dem System
# (z.B. per `cargo install librespot`). Ist librespot nicht installiert,
# läuft die App trotzdem normal weiter - dann eben mit einem externen
# Connect-Ziel wie bisher.
SPOTIFY_CONNECT_ENABLED = os.getenv("SPOTIFY_CONNECT_ENABLED", "true").lower() == "true"
# Audio-Backend fuer librespot - "pulseaudio" funktioniert meist ohne
# weitere Konfiguration auf einem normalen Ubuntu-Desktop (auch mit
# PipeWire, das PulseAudio-kompatibel ist). Auf dem Pi mit HiFiBerry Amp2
# spaeter eher "alsa" mit passendem --device.
SPOTIFY_CONNECT_BACKEND = os.getenv("SPOTIFY_CONNECT_BACKEND", "rodio")
# Name/Pfad des librespot-Programms - je nach Installationsweg (cargo vs.
# Snap) kann der tatsächliche Befehlsname abweichen (siehe README).
SPOTIFY_CONNECT_BINARY = os.getenv("SPOTIFY_CONNECT_BINARY", "librespot")

# Suchergebnisse werden herausgefiltert, wenn Songtitel, Album- oder
# Interpreten-Name eines dieser Woerter enthaelt (Gross-/Kleinschreibung
# egal). Gedacht, um Content-Creator-Tracks (Gaming-YouTuber, Diss-Tracks,
# TikTok-Sounds etc.) aus der Suche fernzuhalten. Liste einfach erweitern,
# ohne Code aendern zu muessen.
SEARCH_EXCLUDED_KEYWORDS = [
    "tiktok",
    "tik tok",
    "gta",
    "grand theft auto",
    "brawl stars",
    "brawlstars",
    "brawl-stars",
    "fortnite",
    "roblox",
]

# Gezielt einzelne Interpreten ausschliessen (z.B. bestimmte YouTube-/
# Content-Creator-Kanaele), die die Keyword-Liste oben nicht erwischt.
# Liste einfach erweitern, sobald dir weitere auffallen. Es gibt keine
# seriöse, vorgefertigte "Liste aller Content Creator" - nur Namen aufnehmen,
# bei denen wirklich bestaetigt ist, dass sie Musik/Content auf Spotify
# veroeffentlicht haben, sonst blockiert man versehentlich legitime Treffer.
SEARCH_EXCLUDED_ARTISTS = [
    "lukasbs",
    "knossi",
    "montanablack",
    "gronkh",
    # Vom Nutzer explizit genannt:
    "puki",
    "clashgames",
    "landi brawl stars",
    "chiefavalon",
    "pookie",
    "gleggmire",
    "elotrix",
    "heideltrautvod",
    "trymacs",
    "csyon",
    "onearly",
    "jojonas",
    "nuno-brawlstars",
]

# --- Drehencoder (nur relevant wenn PLATFORM=pi) ---------------------------
ENCODER_CLK_PIN = int(os.getenv("ENCODER_CLK_PIN", 17))
ENCODER_DT_PIN = int(os.getenv("ENCODER_DT_PIN", 27))
ENCODER_SW_PIN = int(os.getenv("ENCODER_SW_PIN", 22))

# GPIO-Aus-Knopf (nur relevant wenn PLATFORM=pi) - faehrt den Pi sauber
# herunter statt einfach den Stecker zu ziehen (schuetzt die SD-Karte).
# Auf "false" setzen, falls (noch) kein Knopf angeschlossen ist - verhindert
# falsche Ausloeser durch einen frei schwebenden, nicht verbundenen Pin.
SHUTDOWN_BUTTON_PIN = int(os.getenv("SHUTDOWN_BUTTON_PIN", 26))
SHUTDOWN_BUTTON_HOLD_SECONDS = float(os.getenv("SHUTDOWN_BUTTON_HOLD_SECONDS", 3))
SHUTDOWN_BUTTON_ENABLED = os.getenv("SHUTDOWN_BUTTON_ENABLED", "true").lower() == "true"
