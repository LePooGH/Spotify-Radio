"""
Einmalige Neuanmeldung bei Spotify, z.B. wenn neue Berechtigungen (Scopes)
dazugekommen sind. Laeuft auf dem Pi im Terminal, der Browser-Teil kann auf
einem anderen Geraet (Laptop/Handy) erledigt werden:

    cd ~/Spotify-Radio && sudo systemctl stop spotify-radio.service
    venv/bin/python tools/spotify_relogin.py
    sudo systemctl start spotify-radio.service

1. Die angezeigte Adresse am Laptop oeffnen und mit dem Spotify-Konto des
   Radios anmelden.
2. Spotify leitet danach auf http://127.0.0.1:5000/callback?code=... um -
   diese Seite laedt am Laptop nicht (Fehlerseite ist normal).
3. Die komplette Adresse aus der Adresszeile kopieren und hier einfuegen.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth

from modules.spotify_module import SCOPE

load_dotenv(".env")
auth = SpotifyOAuth(
    client_id=os.getenv("SPOTIFY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
    redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
    scope=SCOPE,
    cache_path=".spotify_cache",
    open_browser=False,
)
print("\n=== Spotify-Neuanmeldung ===")
print("1. Diese Adresse am Laptop oeffnen und mit dem Konto des Radios anmelden:\n")
print(auth.get_authorize_url())
print("\n2. Danach die komplette Adresse der (fehlgeschlagenen) Zielseite")
print("   http://127.0.0.1:5000/callback?code=... hier einfuegen und Enter druecken.\n")
redirected = input("Adresse: ").strip()
code = auth.parse_response_code(redirected)
auth.get_access_token(code, as_dict=False, check_cache=False)
sp = spotipy.Spotify(auth_manager=auth)
me = sp.me()
total = sp.current_user_saved_tracks(limit=1).get("total")
print(f"\nAngemeldet als: {me.get('id')}  |  Lieblingssongs: {total}")
print("Fertig - jetzt den Dienst wieder starten: sudo systemctl start spotify-radio.service")
