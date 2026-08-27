"""
Spotify-Radio - Flask-Backend

Laeuft unveraendert auf dem Ubuntu-Entwicklungslaptop und spaeter auf dem
Raspberry Pi. config.PLATFORM entscheidet, welche Hardware-Module aktiv sind
(siehe modules/input_controller.py fuer den Drehencoder).
"""
import atexit
import os
import threading
import time

from flask import Flask, jsonify, render_template, request, redirect, url_for

import config
from modules.spotify_module import SpotifyModule
from modules.spotify_connect import SpotifyConnectDaemon
from modules.external_search import ExternalSearchModule
from modules.updater import Updater
from modules.player import MPVPlayer
from modules.webradio_module import WebRadioModule
from modules.usb_module import USBModule
from modules.input_controller import InputController
from modules.shutdown_button import ShutdownButton

app = Flask(__name__)


@app.context_processor
def inject_asset_url():
    """Haengt an CSS/JS-Dateien automatisch das Aenderungsdatum als
    Cache-Buster an (z.B. style.css?v=1751812345). Ohne das koennte der
    Browser nach einem Update weiterhin die alte, zwischengespeicherte
    Version anzeigen, obwohl der Code auf dem Server laengst neu ist -
    genau das sorgte im Chat-Verlauf mehrfach fuer "es hat sich nichts
    geaendert"-Verwirrung."""
    def asset_url(filename):
        filepath = os.path.join(app.static_folder, filename)
        try:
            version = int(os.path.getmtime(filepath))
        except OSError:
            version = 0
        return f"{url_for('static', filename=filename)}?v={version}"
    return {"asset_url": asset_url}


# --- Module initialisieren --------------------------------------------------

spotify = SpotifyModule(
    client_id=config.SPOTIFY_CLIENT_ID,
    client_secret=config.SPOTIFY_CLIENT_SECRET,
    redirect_uri=config.SPOTIFY_REDIRECT_URI,
    device_name=config.SPOTIFY_DEVICE_NAME,
    excluded_keywords=config.SEARCH_EXCLUDED_KEYWORDS,
    excluded_artists=config.SEARCH_EXCLUDED_ARTISTS,
)

# Externe Diskografie-Vorab-Suche (iTunes Search API) - siehe Chat-Verlauf:
# Statt bei Spotify direkt eine komplette (evtl. sehr umfangreiche)
# Diskografie zu crawlen, wird zuerst eine externe, unlimitierte Datenbank
# befragt. Erst wenn der Nutzer ein konkretes Ergebnis daraus auswaehlt,
# startet eine einzelne, gezielte Spotify-Suche nur dafuer.
external_search = ExternalSearchModule()

# Selbst-Update ueber Git/GitHub (siehe modules/updater.py) - der Button im
# Interface erscheint nur, wenn tatsaechlich eine neuere Version im
# konfigurierten Remote-Repository verfuegbar ist.
updater = Updater(
    repo_path=os.path.dirname(os.path.abspath(__file__)),
    branch=config.UPDATE_BRANCH,
)

# Eigener Spotify-Connect-Client (librespot) im Hintergrund, damit die App
# selbst als Wiedergabeziel erscheint - keine separate Spotify-App noetig
# (siehe modules/spotify_connect.py fuer das einmalige Kopplungs-Setup).
# Startet nur, wenn in der Konfiguration aktiviert; ist librespot nicht
# installiert, laeuft die App trotzdem normal mit einem externen Ziel weiter.
spotify_connect_daemon = None
if config.SPOTIFY_CONNECT_ENABLED:
    spotify_connect_daemon = SpotifyConnectDaemon(
        device_name=config.SPOTIFY_DEVICE_NAME,
        backend=config.SPOTIFY_CONNECT_BACKEND,
        binary_name=config.SPOTIFY_CONNECT_BINARY,
    )
    spotify_connect_daemon.start()
    atexit.register(spotify_connect_daemon.stop)

# Web-Radio und USB teilen sich denselben mpv-Player, da am Ende ohnehin nur
# eine lokale Audioausgabe existiert.
shared_player = MPVPlayer()
webradio = WebRadioModule(shared_player)
usb = USBModule(shared_player, platform=config.PLATFORM)

SOURCES = {"spotify": spotify, "webradio": webradio, "usb": usb}
active_source = {"name": "spotify"}


def _current_module():
    return SOURCES[active_source["name"]]


def _set_volume(level):
    module = _current_module()
    module.set_volume(level) if hasattr(module, "set_volume") else shared_player.set_volume(level)


def _stop_current_source():
    """Beendet die aktuell aktive Quelle vollstaendig (nicht nur pausiert),
    damit beim Quellenwechsel nie zwei Quellen gleichzeitig Ton ausgeben und
    die Audio-Hardware fuer die neue Quelle frei ist."""
    module = _current_module()
    try:
        if hasattr(module, "stop"):
            module.stop()
        else:
            module.pause()
    except Exception:
        pass


# --- Drehencoder-Callbacks (nur wirksam wenn PLATFORM=pi) --------------------

def _handle_encoder_volume(direction):
    step = 5 * direction
    try:
        current = _current_module().get_status().get("volume_percent") or 50
    except Exception:
        current = 50
    _set_volume(max(0, min(100, current + step)))


def _handle_encoder_click():
    module = _current_module()
    try:
        is_playing = module.get_status().get("is_playing")
    except Exception:
        is_playing = False
    module.pause() if is_playing else module.resume()


input_controller = InputController(
    platform=config.PLATFORM,
    on_volume_change=_handle_encoder_volume,
    on_button_press=_handle_encoder_click,
    clk_pin=config.ENCODER_CLK_PIN,
    dt_pin=config.ENCODER_DT_PIN,
    sw_pin=config.ENCODER_SW_PIN,
)

shutdown_button = ShutdownButton(
    platform=config.PLATFORM,
    pin=config.SHUTDOWN_BUTTON_PIN,
    hold_seconds=config.SHUTDOWN_BUTTON_HOLD_SECONDS,
    enabled=config.SHUTDOWN_BUTTON_ENABLED,
)


# --- Web-Oberflaeche ----------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", spotify_authenticated=spotify.is_authenticated())


# --- Spotify-Login (einmaliger OAuth-Flow) -----------------------------------

@app.route("/login")
def login():
    return redirect(spotify.get_auth_url())


@app.route("/callback")
def callback():
    code = request.args.get("code")
    if code:
        spotify.handle_callback(code)
    return redirect("/")


# --- Quellenwahl --------------------------------------------------------------

@app.route("/api/source", methods=["POST"])
def set_source():
    name = (request.json or {}).get("source")
    if name not in SOURCES:
        return jsonify({"error": "unbekannte Quelle"}), 400
    # Laufende Wiedergabe der bisherigen Quelle vollstaendig stoppen (nicht nur
    # pausieren), bevor gewechselt wird.
    _stop_current_source()
    active_source["name"] = name
    return jsonify({"source": name})


# --- Gemeinsame Steuerung (Play/Pause/Skip/Volume) ---------------------------

@app.route("/api/status")
def status():
    try:
        data = _current_module().get_status()
    except Exception as exc:
        data = {"active": False, "error": str(exc)}
    data["source"] = active_source["name"]
    data["can_skip"] = hasattr(_current_module(), "next_track")
    return jsonify(data)


@app.route("/api/play", methods=["POST"])
def play():
    _current_module().resume()
    return jsonify({"ok": True})


@app.route("/api/pause", methods=["POST"])
def pause():
    _current_module().pause()
    return jsonify({"ok": True})


@app.route("/api/next", methods=["POST"])
def next_track():
    module = _current_module()
    if hasattr(module, "next_track"):
        module.next_track()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "reason": "Quelle unterstuetzt kein Skip"}), 400


@app.route("/api/previous", methods=["POST"])
def previous_track():
    module = _current_module()
    if hasattr(module, "previous_track"):
        module.previous_track()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "reason": "Quelle unterstuetzt kein Zurueckspringen"}), 400


@app.route("/api/volume", methods=["POST"])
def volume():
    level = int((request.json or {}).get("level", 50))
    _set_volume(level)
    return jsonify({"ok": True, "level": level})


# --- Spotify-Suche ------------------------------------------------------------

@app.route("/api/spotify/search")
def spotify_search():
    search_type = request.args.get("type", "track")
    offset = int(request.args.get("offset", 0))
    try:
        return jsonify(spotify.search(request.args.get("q", ""), search_type=search_type, offset=offset))
    except Exception as exc:
        # Fehler (z.B. abgelaufener Login, Netzwerkproblem) sichtbar machen,
        # statt dass das Frontend nur stumm leer bleibt.
        return jsonify({"error": str(exc)}), 500


@app.route("/api/spotify/search_combined")
def spotify_search_combined():
    """Sucht Titel und Alben gleichzeitig - fuer die Zwei-Spalten-Ansicht,
    bei der kein Umschalten zwischen Reitern noetig ist."""
    try:
        return jsonify(spotify.search_combined(request.args.get("q", "")))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/spotify/album/<album_id>/tracks")
def spotify_album_tracks(album_id):
    """Liefert die Titel eines Albums fuer die eingerueckte Anzeige nach
    Klick auf ein Album."""
    try:
        return jsonify(spotify.get_album_tracks(album_id))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/external/search")
def external_search_route():
    """Externe Diskografie-Vorab-Suche (iTunes) - KEINE Spotify-Anfrage.
    Liefert Text + Cover, aber noch keine abspielbaren Spotify-URIs."""
    query = request.args.get("q", "")
    if not query:
        return jsonify([])
    return jsonify(external_search.search_albums(query))


@app.route("/api/spotify/search_for_album")
def spotify_search_for_album():
    """Gezielte, einmalige Spotify-Suche fuer EIN aus der externen
    Vorab-Suche ausgewaehltes Ergebnis - siehe SpotifyModule.
    search_album_by_hint. Der Titel wird dabei um Folgen-/Episoden-
    Nummerierungen bereinigt (siehe ExternalSearchModule.
    simplify_title_for_search), da diese zwischen der externen Quelle und
    Spotify oft unterschiedlich formatiert sind."""
    artist = request.args.get("artist", "")
    title = request.args.get("title", "")
    simplified_title = external_search.simplify_title_for_search(title)
    try:
        return jsonify(spotify.search_album_by_hint(artist, simplified_title))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/spotify/last_played")
def spotify_last_played():
    """Liefert den zuletzt gespielten Titel (Festplatten-Zwischenspeicherung)
    - fuers Anzeigen von 'Aktuelles Album' schon vor der ersten echten
    Wiedergabe nach einem App-Start."""
    return jsonify(spotify.get_last_played() or {})


@app.route("/api/spotify/devices")
def spotify_devices():
    return jsonify(spotify.list_devices())


@app.route("/api/spotify/device", methods=["POST"])
def spotify_set_device():
    device_id = (request.json or {}).get("device_id")
    if not device_id:
        return jsonify({"error": "device_id fehlt"}), 400
    spotify.set_device(device_id)
    return jsonify({"ok": True})


@app.route("/api/spotify/play", methods=["POST"])
def spotify_play():
    uri = (request.json or {}).get("uri")
    active_source["name"] = "spotify"
    spotify.play_uri(uri)
    return jsonify({"ok": True})


@app.route("/api/spotify/playlists")
def spotify_playlists():
    try:
        return jsonify(spotify.get_user_playlists())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/spotify/playlist/<playlist_id>/tracks")
def spotify_playlist_tracks(playlist_id):
    try:
        return jsonify(spotify.get_playlist_tracks(playlist_id))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/spotify/playlist/play", methods=["POST"])
def spotify_playlist_play():
    playlist_id = (request.json or {}).get("playlist_id")
    if not playlist_id:
        return jsonify({"error": "playlist_id fehlt"}), 400
    active_source["name"] = "spotify"
    try:
        spotify.play_uri(f"spotify:playlist:{playlist_id}")
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/spotify/playlist/add", methods=["POST"])
def spotify_playlist_add():
    data = request.json or {}
    playlist_id = data.get("playlist_id")
    uri = data.get("uri")
    if not playlist_id or not uri:
        return jsonify({"error": "playlist_id oder uri fehlt"}), 400
    try:
        spotify.add_track_to_playlist(playlist_id, uri)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/spotify/repeat", methods=["POST"])
def spotify_repeat():
    mode = (request.json or {}).get("mode", "off")
    try:
        spotify.set_repeat(mode)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/spotify/shuffle", methods=["POST"])
def spotify_shuffle():
    enabled = (request.json or {}).get("enabled", False)
    try:
        spotify.set_shuffle(enabled)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


# --- Web-Radio ----------------------------------------------------------------

@app.route("/api/radio/search")
def radio_search():
    return jsonify(webradio.search(request.args.get("q", "")))


@app.route("/api/radio/play", methods=["POST"])
def radio_play():
    data = request.json or {}
    active_source["name"] = "webradio"
    webradio.play(data.get("url"), data.get("name"))
    return jsonify({"ok": True})


# --- USB / MP3 -----------------------------------------------------------------

@app.route("/api/usb/devices")
def usb_devices():
    return jsonify(usb.list_devices())


@app.route("/api/usb/device", methods=["POST"])
def usb_set_device():
    path = (request.json or {}).get("path")
    if not path:
        return jsonify({"error": "path fehlt"}), 400
    usb.set_device(path)
    return jsonify({"ok": True})


@app.route("/api/usb/eject", methods=["POST"])
def usb_eject():
    path = (request.json or {}).get("path")
    if not path:
        return jsonify({"error": "path fehlt"}), 400
    try:
        return jsonify(usb.eject_device(path))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.route("/api/usb/list")
def usb_list():
    return jsonify(usb.list_tracks())


@app.route("/api/usb/browse")
def usb_browse():
    """Liefert den Inhalt einer Ordnerebene (Wurzel, falls kein path
    angegeben) - Ordner links zum Weiterklicken, Dateien dieser Ebene rechts."""
    path = request.args.get("path")
    return jsonify(usb.browse_path(path))


@app.route("/api/usb/folder_tracks")
def usb_folder_tracks():
    path = request.args.get("path", "")
    return jsonify(usb.list_tracks_in_folder(path))


@app.route("/api/usb/folder/play", methods=["POST"])
def usb_folder_play():
    path = (request.json or {}).get("path")
    if not path:
        return jsonify({"error": "path fehlt"}), 400
    active_source["name"] = "usb"
    usb.play_folder(path)
    return jsonify({"ok": True})


@app.route("/api/usb/play", methods=["POST"])
def usb_play():
    path = (request.json or {}).get("path")
    active_source["name"] = "usb"
    usb.play(path)
    return jsonify({"ok": True})


# --- Selbst-Update ueber Git/GitHub -------------------------------------------

@app.route("/api/update/check")
def update_check():
    return jsonify(updater.check_for_update())


@app.route("/api/update/apply", methods=["POST"])
def update_apply():
    result = updater.apply_update()
    if result.get("ok"):
        # App nach kurzer Verzoegerung beenden, damit die Erfolgsmeldung
        # noch beim Browser ankommt, bevor der Prozess weg ist. Auf dem Pi
        # (systemd-Service mit Restart=on-failure, siehe deploy/) startet
        # sie sich dadurch automatisch mit dem neuen Code neu - im
        # Dev-Modus (kein systemd) muss "python app.py" danach manuell neu
        # gestartet werden.
        def _delayed_exit():
            time.sleep(1)
            os._exit(0)
        threading.Thread(target=_delayed_exit, daemon=True).start()
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=(config.PLATFORM == "dev"))
