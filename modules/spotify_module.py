"""
Spotify-Modul: Kapselt alle Interaktionen mit der Spotify Web API.

Wichtig: Dieses Modul spielt keine Musik selbst ab, sondern steuert per
Fernbedienung ein Spotify-Connect-Zielgeraet - im Dev-Modus z.B. dein Handy
mit geoeffneter Spotify-App, spaeter auf dem Pi raspotify/librespot.
"""
import re
import time

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from modules.disk_cache import DiskCache

SCOPE = (
    "user-modify-playback-state user-read-playback-state "
    "user-read-currently-playing playlist-read-private "
    "playlist-read-collaborative playlist-modify-public playlist-modify-private"
)

# Sortier-Muster fuer Hörspiel-Diskografien wie "Die drei ???":
# 1. Titel mit vorangestellter Nummer + Schraegstrich (z.B. "264/Der Fluch..."),
#    absteigend nach Nummer (neueste zuerst)
# 2. Titel im Format "FolgeXX" / "Folge XX", ebenfalls absteigend nach Nummer
# 3. Alles andere, alphabetisch
_NUMBER_PREFIX_RE = re.compile(r"^\s*(\d+)\s*/")
_FOLGE_RE = re.compile(r"^\s*folge\s*(\d+)", re.IGNORECASE)

# Ersatz fuer die von Spotify im Februar 2026 entfernte Top-Tracks-API und das
# ebenfalls entfernte popularity-Feld: Titel eines offiziellen "Best Of"-/
# "Greatest Hits"-Kompilationsalbums werden als Naeherung fuer "meistgehoerte
# Songs" verwendet, falls die Diskografie ein solches Album enthaelt.
_BEST_OF_KEYWORDS = [
    "greatest hits", "best of", "the best of", "very best of", "essential",
    "anthology", "ultimate collection", "number ones", "the hits",
    "hits collection", "collection",
]

# Begrenzung fuer die Katalog-Abfrage eines Interpreten (siehe
# _fetch_artist_catalog): maximal so viele Seiten a 10 Eintraege. Schuetzt
# vor einer echten Endlosschleife bei absurd umfangreichen Katalogen, ist
# aber grosszuegig genug, um auch sehr umfangreiche Hoerspielserien
# vollstaendig zu erfassen (50 Seiten = 500 Eintraege).
_CATALOG_MAX_PAGES = 50


class SpotifyModule:
    def __init__(self, client_id, client_secret, redirect_uri, device_name=None,
                 cache_path=".spotify_cache", excluded_keywords=None, excluded_artists=None):
        self.device_name = device_name
        # Vom Nutzer explizit im Interface ausgewaehltes Ziel-Geraet.
        # Hat Vorrang vor der (nur als Fallback gedachten) device_name-Heuristik.
        self.selected_device_id = None
        # Merkt sich, welches Geraet bereits per transfer_playback
        # "aktiviert" wurde (siehe _ensure_activated) - verhindert
        # wiederholte, unnoetige transfer_playback-Aufrufe fuer dasselbe
        # Geraet innerhalb derselben Sitzung.
        self._activated_device_id = None
        # Suchergebnisse werden herausgefiltert, wenn Songtitel/Album/Interpret
        # eines dieser Woerter enthaelt bzw. einer dieser Interpreten ist.
        # Konfiguriert in config.py, damit man die Liste ohne Code-Aenderung
        # erweitern kann.
        self.excluded_keywords = [k.lower() for k in (excluded_keywords or [])]
        self.excluded_artists = [a.lower() for a in (excluded_artists or [])]
        # Cache: Interpreten-ID -> komplette, sortierte, gefilterte
        # Alben-Liste. Noetig, damit die Sortierung ueber die gesamte
        # Diskografie stimmt statt nur innerhalb einzelner 10er-Haeppchen
        # (siehe _fetch_full_discography).
        self._discography_cache = {}
        # Cache: Interpreten-ID -> Titelliste des gefundenen Best-Of-Albums
        # (oder None, wenn keins gefunden wurde) - siehe _fetch_top_tracks_proxy.
        self._top_tracks_cache = {}
        # Cache: Interpreten-ID -> kompletter Roh-Katalog (Alben+Singles+
        # Kompilationen zusammen). Wird EINMAL pro Interpret geladen und fuer
        # sowohl die Alben-Spalte als auch die Best-Of-Suche der Titel-Spalte
        # wiederverwendet - sonst wuerden zwei komplette, separate
        # Diskografie-Abfragen noetig sein, was schnell in Spotifys
        # Rate-Limit fuer Development-Mode-Apps laeuft (siehe Chat-Verlauf:
        # ein einzelner 429 kann dort einen fast 24h-Timeout bedeuten).
        self._catalog_cache = {}
        # Cache: Suchbegriff (klein geschrieben) -> aufgeloeste Interpreten-ID
        # (oder None). Vermeidet wiederholte "type=artist"-Anfragen bei
        # wiederholten Suchen desselben Begriffs.
        self._artist_id_cache = {}
        # Zusaetzlich zu den beiden In-Memory-Caches oben: eine dateibasierte
        # Zwischenspeicherung (24h Ablaufzeit), die auch App-Neustarts
        # ueberlebt - sonst waere z.B. eine erneute Suche nach einem
        # umfangreichen Interpreten (200+ Eintraege) nach jedem Neustart
        # wieder ein kompletter, teurer Crawl, was Spotifys Rate-Limit
        # ausloesen kann (siehe Chat-Verlauf).
        self._catalog_disk_cache = DiskCache(".spotify_catalog_cache.json")
        self._artist_id_disk_cache = DiskCache(".spotify_artist_id_cache.json")
        # Cache: die eigene Nutzer-ID - noetig, um zu erkennen, ob eine
        # Playlist wirklich einem selbst gehoert (siehe get_user_playlists).
        self._current_user_id = None
        # Cache: Playlist-ID -> Titelliste. Ohne das wuerde jeder erneute
        # Klick auf dieselbe Playlist die komplette Titelliste nochmal
        # abfragen - bei einer grossen Playlist (mehrere hundert Titel)
        # waeren das viele Anfragen in Folge, jedes Mal wieder.
        self._playlist_tracks_cache = {}
        # Cache: die eigene Playlist-Liste selbst (aendert sich selten
        # innerhalb einer Sitzung).
        self._user_playlists_cache = None
        self._auth_manager = SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope=SCOPE,
            cache_path=cache_path,
            open_browser=False,
        )
        self.sp = spotipy.Spotify(auth_manager=self._auth_manager)

    def is_authenticated(self):
        return self._auth_manager.get_cached_token() is not None

    def get_auth_url(self):
        return self._auth_manager.get_authorize_url()

    def handle_callback(self, code):
        self._auth_manager.get_access_token(code, as_dict=False)

    def list_devices(self):
        """Liste aller aktuell verfuegbaren Spotify-Connect-Geraete
        (Handy, Computer, spaeter raspotify auf dem Pi, ...)."""
        devices = self.sp.devices().get("devices", [])
        return [
            {
                "id": d["id"],
                "name": d["name"],
                "type": d["type"],
                "is_active": d["is_active"],
            }
            for d in devices
        ]

    def set_device(self, device_id):
        """Setzt das Ziel-Geraet fest und verschiebt eine laufende Wiedergabe
        dorthin (falls gerade etwas spielt)."""
        self.selected_device_id = device_id
        try:
            self.sp.transfer_playback(device_id, force_play=False)
        except spotipy.SpotifyException:
            pass  # z.B. wenn aktuell nichts spielt - kein Problem
        self._activated_device_id = device_id

    def _find_device_by_name(self, devices):
        for d in devices:
            if self.device_name.lower() in d["name"].lower():
                return d["id"]
        return None

    def _clear_device_cache(self):
        """Verwirft das zwischengespeicherte Geraet (siehe _get_device_id) -
        wird aufgerufen, wenn ein Wiedergabebefehl fehlschlaegt, z.B. weil
        das Geraet zwischenzeitlich offline gegangen ist. Der naechste
        _get_device_id()-Aufruf sucht dann wieder frisch."""
        self._activated_device_id = None

    def _ensure_activated(self, device_id):
        """Ein Geraet, das in dieser Sitzung noch nie als aktives
        Wiedergabeziel gesetzt wurde (z.B. gerade erst per Zeroconf
        gekoppeltes librespot direkt nach dem App-Start), nimmt
        Wiedergabebefehle manchmal nicht zuverlaessig an, bis es einmal
        per transfer_playback aktiviert wurde - das passiert normalerweise
        automatisch im Hintergrund, wenn man ein Geraet manuell im
        Interface auswaehlt (siehe set_device). Bei der automatischen
        Namens-Erkennung wird das hier nachgeholt, damit dafuer kein
        manueller Klick noetig ist."""
        if self._activated_device_id == device_id:
            return
        try:
            self.sp.transfer_playback(device_id, force_play=False)
        except spotipy.SpotifyException:
            pass
        self._activated_device_id = device_id

    def _get_device_id(self):
        """Ermittelt das Ziel-Connect-Geraet: zuerst die explizite Auswahl aus
        dem Interface, sonst ein bereits in dieser Sitzung gefundenes/
        aktiviertes Geraet (schneller Pfad - keine erneute Geraeteliste
        noetig), sonst die device_name-Heuristik aus der .env, sonst einfach
        das erste verfuegbare Geraet.

        Wichtig fuer die Reaktionsgeschwindigkeit: Ohne den schnellen Pfad
        wuerde JEDER Play/Pause/Weiter/Zurueck-Tastendruck zusaetzlich zum
        eigentlichen Befehl noch eine komplette Geraeteliste bei Spotify
        abfragen - zwei Anfragen statt einer, was sich bei jedem Tastendruck
        spuerbar traege anfuehlt. Stattdessen wird das einmal gefundene
        Geraet fuer den Rest der Sitzung direkt wiederverwendet; schlaegt ein
        Wiedergabebefehl damit fehl (z.B. weil das Geraet zwischenzeitlich
        offline gegangen ist), wird der Cache verworfen (siehe
        _clear_device_cache) und beim naechsten Versuch neu gesucht.

        Falls das Namens-Geraet (z.B. das selbstverwaltete librespot) beim
        ersten Versuch noch nicht in der Liste auftaucht, wird bis zu 20
        Sekunden lang alle 2 Sekunden erneut nachgefragt, bevor auf ein
        anderes Geraet zurueckgefallen wird - direkt nach dem App-Start
        (Kaltstart) kann es so lange dauern, bis librespot bei Spotify
        vollstaendig als steuerbares Geraet registriert ist, auch wenn der
        lokale Prozess selbst schon laeuft."""
        if self.selected_device_id:
            return self.selected_device_id
        if self._activated_device_id:
            return self._activated_device_id

        devices = self.sp.devices().get("devices", [])
        if self.device_name:
            match = self._find_device_by_name(devices)
            if match:
                self._ensure_activated(match)
                return match
            for _ in range(10):
                time.sleep(2)
                devices = self.sp.devices().get("devices", [])
                match = self._find_device_by_name(devices)
                if match:
                    self._ensure_activated(match)
                    return match

        return devices[0]["id"] if devices else None

    def _is_excluded(self, text_parts):
        """Prueft, ob einer der zu durchsuchenden Texte (Songtitel, Album,
        Interpret) ein ausgeschlossenes Schluesselwort enthaelt oder von
        einem ausgeschlossenen Interpreten stammt."""
        haystack = " ".join(p for p in text_parts if p).lower()
        if any(keyword in haystack for keyword in self.excluded_keywords):
            return True
        if any(artist in haystack for artist in self.excluded_artists):
            return True
        return False

    def _format_and_filter(self, items, item_type):
        """Formatiert Titel- oder Album-Rohdaten aus der Spotify-API in ein
        einheitliches Format und wendet dabei den Content-Creator-Filter an."""
        results = []
        for item in items:
            artist_names = [a["name"] for a in item["artists"]]
            if item_type == "track":
                album_name = item["album"]["name"]
                cover = item["album"]["images"][0]["url"] if item["album"]["images"] else None
            else:
                album_name = item["name"]
                cover = item["images"][0]["url"] if item["images"] else None

            if self._is_excluded([item["name"], album_name, *artist_names]):
                continue

            results.append({
                "uri": item["uri"],
                "name": item["name"],
                "artist": ", ".join(artist_names),
                "album_cover": cover,
                "type": item_type,
            })
        return results

    def _album_sort_key(self, album):
        """Dreistufiges Sortier-Schema, zugeschnitten auf Hörspiel-Diskografien:
        1. Nummer-Schraegstrich-Titel ("264/...") absteigend nach Nummer
        2. "FolgeXX"-Titel absteigend nach Nummer
        3. Alles andere alphabetisch
        Da die Kategorie immer zuerst verglichen wird, werden die
        unterschiedlichen Typen im zweiten Element (int vs. str) nie
        gegeneinander verglichen - das ist sicher."""
        name = album.get("name") or ""
        m = _NUMBER_PREFIX_RE.match(name)
        if m:
            return (0, -int(m.group(1)))
        m = _FOLGE_RE.match(name)
        if m:
            return (1, -int(m.group(1)))
        return (2, name.lower())

    def _resolve_artist_id(self, query):
        """Versucht, die Suchanfrage einem konkreten Interpreten zuzuordnen.
        Wird genutzt, um bei einer Interpreten-Suche dessen echte, komplette
        Diskografie zu zeigen statt der unsortierten, relevanzbasierten
        Album-Suche. Ergebnis wird pro Suchbegriff im Arbeitsspeicher UND
        auf der Festplatte (24h) gecacht, damit auch ein App-Neustart keine
        erneute "type=artist"-Anfrage bei Spotify ausloest."""
        key = query.strip().lower()
        if key in self._artist_id_cache:
            return self._artist_id_cache[key]

        cached = self._artist_id_disk_cache.get(key)
        if cached is not None:
            # In ein Dict gewickelt, damit "kein Interpret gefunden"
            # (artist_id=None) von "gar nicht im Cache" unterscheidbar ist.
            artist_id = cached.get("id")
            self._artist_id_cache[key] = artist_id
            return artist_id

        try:
            raw = self.sp.search(q=query, type="artist", limit=1)
            items = raw.get("artists", {}).get("items", [])
            artist_id = items[0]["id"] if items else None
        except spotipy.SpotifyException:
            artist_id = None
        self._artist_id_cache[key] = artist_id
        self._artist_id_disk_cache.set(key, {"id": artist_id})
        return artist_id

    def _dedupe_by_name(self, items):
        """Diskografien enthalten oft Duplikate (z.B. verschiedene
        Laender-Releases desselben Albums) - nach Namen deduplizieren."""
        seen = set()
        deduped = []
        for album in items:
            key = album["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(album)
        return deduped

    def _fetch_artist_catalog(self, artist_id):
        """Laedt den Roh-Katalog eines Interpreten (Alben+Singles+
        Kompilationen zusammen) in EINEM gemeinsamen, begrenzten Durchlauf.
        Wird sowohl fuer die Alben-Spalte (_albums_for_query) als auch fuer
        die Best-Of-Suche der Titel-Spalte (_find_best_of_album) verwendet -
        dadurch reicht eine einzige Diskografie-Abfrage pro Interpret statt
        zwei komplett getrennter, was die Zahl der Spotify-Anfragen deutlich
        reduziert (wichtig wegen Spotifys Rate-Limit fuer Development-Mode-
        Apps: eine einzelne 429-Antwort kann dort eine fast 24h-Sperre nach
        sich ziehen).

        Begrenzt auf maximal _CATALOG_MAX_PAGES Seiten a 10 Eintraege (siehe
        Konstante oben) - grosszuegig genug fuer auch sehr umfangreiche
        Diskografien (z.B. jahrzehntelange Hoerspielserien), aber mit einer
        kleinen Pause zwischen den Anfragen, um Spotifys Kurzzeit-Burst-
        Limit nicht zu triggern. Das Ergebnis wird pro Interpret fuer die
        Dauer der laufenden App-Sitzung gecacht (siehe _get_artist_catalog) -
        dieser (etwas laengere) Crawl passiert also nur EINMAL pro
        Interpret, nicht bei jeder erneuten Suche."""
        items = []
        offset = 0
        for page in range(_CATALOG_MAX_PAGES):
            if page > 0:
                time.sleep(0.15)  # kleine Pause gegen Burst-Rate-Limits
            raw = self.sp.artist_albums(
                artist_id, album_type="album,single,compilation", limit=10, offset=offset
            )
            batch = raw.get("items", [])
            items.extend(batch)
            if len(batch) < 10:
                break
            offset += 10
        return self._dedupe_by_name(items)

    def _get_artist_catalog(self, artist_id):
        if artist_id in self._catalog_cache:
            return self._catalog_cache[artist_id]

        cached = self._catalog_disk_cache.get(artist_id)
        if cached is not None:
            self._catalog_cache[artist_id] = cached
            return cached

        catalog = self._fetch_artist_catalog(artist_id)
        self._catalog_cache[artist_id] = catalog
        self._catalog_disk_cache.set(artist_id, catalog)
        return catalog

    def _is_best_of_album(self, album):
        name = (album.get("name") or "").lower()
        return any(kw in name for kw in _BEST_OF_KEYWORDS)

    def _find_best_of_album(self, artist_id):
        """Sucht ein offizielles 'Best Of'/'Greatest Hits'-Kompilationsalbum
        im (gemeinsam gecachten) Katalog eines Interpreten. Gibt die
        Album-ID zurueck, oder None, wenn nichts Passendes gefunden wurde.
        Bei mehreren Treffern wird das mit den meisten Titeln bevorzugt
        (meist die umfangreichste/offizielle Sammlung)."""
        catalog = self._get_artist_catalog(artist_id)
        candidates = [a for a in catalog if self._is_best_of_album(a)]
        if not candidates:
            return None
        candidates.sort(key=lambda a: a.get("total_tracks") or 0, reverse=True)
        return candidates[0]["id"]

    def _fetch_album_tracks_raw(self, album_id, cap):
        """Holt bis zu `cap` Titel eines Albums, paginiert mit dem seit
        Februar 2026 geltenden Limit von 10 pro Anfrage.

        Wichtig (wie schon bei get_playlist_tracks - siehe dort fuer den
        identischen Fehler bei Playlists): Ob es weitere Seiten gibt, wird
        NICHT anhand der Batch-Groesse entschieden - Spotify liefert manchmal
        weniger Eintraege pro Seite zurueck als angefragt, obwohl noch mehr
        Daten existieren. Ein Batch kleiner als das Limit bedeutet also NICHT
        zuverlaessig "keine weiteren Titel mehr" - stattdessen wird das
        "next"-Feld der Spotify-Antwort selbst geprueft, das das korrekt
        angibt."""
        items = []
        offset = 0
        while len(items) < cap:
            raw = self.sp.album_tracks(album_id, limit=10, offset=offset)
            batch = raw.get("items", [])
            if not batch:
                break
            items.extend(batch)
            if not raw.get("next"):
                break
            offset += len(batch)
        return items[:cap]

    def _fetch_top_tracks_proxy(self, artist_id):
        """Liefert bis zu 40 Titel aus einem gefundenen Best-Of-Album als
        Naeherung fuer 'meistgehoerte Songs' (Spotify hat die echten
        Popularitaets-/Top-Tracks-Daten fuer private Apps im Februar 2026
        gesperrt). Gibt None zurueck, wenn keine passende Kompilation
        existiert - dann greift der Aufrufer auf die normale Suche zurueck."""
        album_id = self._find_best_of_album(artist_id)
        if not album_id:
            return None

        raw_tracks = self._fetch_album_tracks_raw(album_id, cap=40)
        album = self.sp.album(album_id)
        cover = album["images"][0]["url"] if album.get("images") else None

        results = []
        for t in raw_tracks:
            artist_names = [a["name"] for a in t["artists"]]
            if self._is_excluded([t["name"], *artist_names]):
                continue
            results.append({
                "uri": t["uri"],
                "name": t["name"],
                "artist": ", ".join(artist_names),
                "album_cover": cover,
                "type": "track",
            })
        return results

    def _tracks_for_query(self, query, offset, artist_id=None):
        """Liefert einen 10er-Ausschnitt der Titel zu einer Suchanfrage. Bei
        einem Interpreten-Treffer werden bevorzugt die Titel von dessen
        Best-Of-Album genutzt (siehe _fetch_top_tracks_proxy); ohne Treffer
        oder ohne gefundenes Best-Of-Album faellt es auf die normale,
        relevanzbasierte Titel-Suche zurueck.

        artist_id kann von search_combined() bereits aufgeloest uebergeben
        werden, um eine doppelte "type=artist"-Anfrage zu vermeiden (wird
        sonst selbst aufgeloest, ggf. aus dem Cache)."""
        if artist_id is None:
            artist_id = self._resolve_artist_id(query)
        if artist_id:
            if artist_id not in self._top_tracks_cache:
                self._top_tracks_cache[artist_id] = self._fetch_top_tracks_proxy(artist_id)
            cached = self._top_tracks_cache[artist_id]
            if cached is not None:
                return cached[offset:offset + 10]

        raw = self.sp.search(q=query, type="track", limit=10, offset=offset)
        items = raw.get("tracks", {}).get("items", [])
        return self._format_and_filter(items, "track")

    def _albums_for_query(self, query, offset, artist_id=None):
        """Liefert einen 10er-Ausschnitt der Alben zu einer Suchanfrage.

        Wenn die Anfrage einem Interpreten zugeordnet werden kann, wird
        dessen Katalog (gemeinsam mit der Best-Of-Suche gecacht, siehe
        _get_artist_catalog) auf reguläre Alben/Singles gefiltert, global
        sortiert und gecacht - weitere Aufrufe fuer denselben Interpreten
        (z.B. beim Nachladen) blaettern nur noch durch diese bereits fertig
        sortierte Liste, statt erneut bei Spotify anzufragen.

        Ohne Interpreten-Treffer faellt es auf die generische, relevanzbasierte
        Album-Suche zurueck (dort liefert Spotify ohnehin nur max. 10 pro
        Anfrage, seitenweise ueber offset abrufbar).

        artist_id kann von search_combined() bereits aufgeloest uebergeben
        werden, um eine doppelte "type=artist"-Anfrage zu vermeiden."""
        if artist_id is None:
            artist_id = self._resolve_artist_id(query)
        if artist_id:
            if artist_id not in self._discography_cache:
                catalog = self._get_artist_catalog(artist_id)
                # Reine Kompilationen bleiben der Best-Of-Suche vorbehalten,
                # damit die Alben-Spalte nicht mit Zusammenstellungen
                # ueberladen wird, die die eigentliche Diskografie doppeln.
                regular = [a for a in catalog if a.get("album_type") != "compilation"]
                regular.sort(key=self._album_sort_key)
                self._discography_cache[artist_id] = self._format_and_filter(regular, "album")
            full_list = self._discography_cache[artist_id]
            return full_list[offset:offset + 10]

        raw = self.sp.search(q=query, type="album", limit=10, offset=offset)
        items = self._dedupe_by_name(raw.get("albums", {}).get("items", []))
        items.sort(key=self._album_sort_key)
        return self._format_and_filter(items, "album")

    def search(self, query, search_type="track", offset=0):
        """Sucht Titel ODER Alben (fuer Infinite Scroll pro Spalte, das ueber
        offset weiterblaettert).

        Wichtig: Seit den Aenderungen an der Spotify Web API im Februar 2026
        akzeptiert /v1/search maximal limit=10 (vorher 50) - ein hoeherer Wert
        fuehrt zu einem 400-Fehler ("Invalid limit")."""
        if not query:
            return []
        if search_type not in ("track", "album"):
            search_type = "track"

        if search_type == "album":
            return self._albums_for_query(query, offset)

        return self._tracks_for_query(query, offset)

    def search_album_by_hint(self, artist, title, limit=10):
        """Gezielte, EINMALIGE Spotify-Albumsuche fuer ein konkretes Ergebnis
        aus der externen Diskografie-Vorab-Suche (siehe modules/
        external_search.py und Chat-Verlauf) - im Gegensatz zur
        Interpreten-Aufloesung + komplettem Katalog-Crawl (_get_artist_catalog)
        ist das nur eine einzelne, normale Albumsuche, genau wie ein Nutzer
        sie auch manuell eintippen wuerde. Dafuer gedacht, dass man bei sehr
        umfangreichen Diskografien (z.B. Hoerspielserien) nicht jedesmal den
        ganzen Katalog laden muss, sondern nur das eine, bereits ausgewaehlte
        Ergebnis gezielt bei Spotify sucht."""
        query = f"{artist} {title}".strip()
        if not query:
            return []
        raw = self.sp.search(q=query, type="album", limit=limit)
        items = raw.get("albums", {}).get("items", [])
        results = self._format_and_filter(items, "album")
        return self._dedupe_by_name(results)

    def is_query_blocked(self, query):
        """Prueft die Sucheingabe SELBST (nicht nur einzelne Ergebnisse)
        gegen die Ausschlusslisten - z.B. wenn direkt nach einem gesperrten
        Content-Creator gesucht wird. Damit gibt's eine klare Rueckmeldung
        statt einer stillen Leerliste, wenn ohnehin alle Treffer rausgefiltert
        wuerden."""
        return self._is_excluded([query])

    def search_combined(self, query):
        """Sucht Titel UND Alben gleichzeitig - fuer die Zwei-Spalten-Ansicht,
        bei der beides parallel angezeigt wird, ohne dass ein Umschalten
        zwischen Reitern noetig ist. Titel kommen bei einem Interpreten-Treffer
        moeglichst aus dessen Best-Of-Album (siehe _tracks_for_query), Alben
        neueste zuerst (siehe _albums_for_query). Der Interpret wird dabei nur
        EINMAL aufgeloest und an beide weitergereicht, statt es zweimal separat
        zu tun."""
        if not query:
            return {"tracks": [], "albums": []}
        if self.is_query_blocked(query):
            return {"tracks": [], "albums": [], "blocked": True}
        artist_id = self._resolve_artist_id(query)
        tracks = self._tracks_for_query(query, offset=0, artist_id=artist_id)
        albums = self._albums_for_query(query, offset=0, artist_id=artist_id)
        return {"tracks": tracks, "albums": albums}

    def get_album_tracks(self, album_id):
        """Liefert die Titel eines Albums, fuer die eingerueckte Anzeige nach
        Klick auf ein Album in der Ergebnisliste bzw. fuer die
        'Aktuelles Album'-Seitenleiste. Nutzt die paginierte Abfrage (siehe
        _fetch_album_tracks_raw), da /v1/albums/{id}/tracks ebenfalls nur
        begrenzte limit-Werte akzeptiert."""
        raw_tracks = self._fetch_album_tracks_raw(album_id, cap=200)
        results = []
        for t in raw_tracks:
            artist_names = [a["name"] for a in t["artists"]]
            if self._is_excluded([t["name"], *artist_names]):
                continue
            results.append({
                "uri": t["uri"],
                "name": t["name"],
                "artist": ", ".join(artist_names),
                "track_number": t.get("track_number"),
            })
        return results

    def play_uri(self, uri):
        device_id = self._get_device_id()
        if not device_id:
            raise RuntimeError(
                "Kein Spotify-Connect-Geraet gefunden. Ist die Spotify-App "
                "(Dev) bzw. raspotify (Pi) aktiv und im selben Netzwerk?"
            )
        try:
            # Alben (und andere Kontexte wie Playlists) muessen ueber
            # context_uri gestartet werden, einzelne Titel ueber die
            # uris-Liste.
            if ":album:" in uri or ":playlist:" in uri:
                self.sp.start_playback(device_id=device_id, context_uri=uri)
            else:
                self.sp.start_playback(device_id=device_id, uris=[uri])
        except spotipy.SpotifyException:
            self._clear_device_cache()  # Geraet evtl. nicht mehr gueltig - neu suchen beim naechsten Versuch
            raise

    def pause(self):
        device_id = self._get_device_id()
        try:
            self.sp.pause_playback(device_id=device_id)
        except spotipy.SpotifyException:
            self._clear_device_cache()  # Geraet evtl. nicht mehr gueltig - neu suchen beim naechsten Versuch

    def resume(self):
        device_id = self._get_device_id()
        try:
            self.sp.start_playback(device_id=device_id)
        except spotipy.SpotifyException:
            self._clear_device_cache()

    def next_track(self):
        device_id = self._get_device_id()
        try:
            self.sp.next_track(device_id=device_id)
        except spotipy.SpotifyException:
            self._clear_device_cache()

    def previous_track(self):
        device_id = self._get_device_id()
        try:
            self.sp.previous_track(device_id=device_id)
        except spotipy.SpotifyException:
            self._clear_device_cache()

    def set_volume(self, level):
        device_id = self._get_device_id()
        self.sp.volume(int(level), device_id=device_id)

    def get_status(self):
        if not self.is_authenticated():
            return {"active": False}
        current = self.sp.current_playback()
        if not current or not current.get("item"):
            return {"active": False}
        item = current["item"]
        return {
            "active": True,
            "is_playing": current.get("is_playing", False),
            "uri": item["uri"],
            "name": item["name"],
            "artist": ", ".join(a["name"] for a in item["artists"]),
            "album_cover": (item["album"]["images"][0]["url"] if item["album"]["images"] else None),
            "album_id": item["album"]["id"],
            "album_name": item["album"]["name"],
            "progress_ms": current.get("progress_ms"),
            "duration_ms": item.get("duration_ms"),
            "volume_percent": (current.get("device") or {}).get("volume_percent"),
            "device_name": (current.get("device") or {}).get("name"),
            "shuffle_state": current.get("shuffle_state", False),
            "repeat_state": current.get("repeat_state", "off"),
        }

    def set_repeat(self, mode):
        """mode: 'track' (Titel wiederholen), 'context' (Playlist/Album
        wiederholen) oder 'off'."""
        if mode not in ("track", "context", "off"):
            return
        device_id = self._get_device_id()
        self.sp.repeat(mode, device_id=device_id)

    def set_shuffle(self, enabled):
        device_id = self._get_device_id()
        self.sp.shuffle(bool(enabled), device_id=device_id)

    def _get_current_user_id(self):
        if self._current_user_id is None:
            self._current_user_id = self.sp.current_user().get("id")
        return self._current_user_id

    def get_user_playlists(self):
        """Liste der eigenen Playlists (inkl. private/kollaborative dank
        entsprechender Scopes). Wird EINMAL pro App-Sitzung geladen und
        danach gecacht (siehe _user_playlists_cache) - ein erneuter Aufruf
        (z.B. Tab-Wechsel) fragt nicht wieder bei Spotify an. Paginiert
        vorsichtshalber mit limit=10 pro Anfrage - Spotify hat diverse
        Listen-Endpunkte seit Februar 2026 auf dieses Limit gedeckelt, teils
        ohne es in der offiziellen Doku zu erwaehnen (siehe Chat-Verlauf zu
        /artists/{id}/albums) - inklusive einer kleinen Pause zwischen den
        Seiten-Anfragen gegen Kurzzeit-Burst-Limits.

        Jede Playlist bekommt zusaetzlich ein "owned"-Flag: Spotify liefert
        seit Februar 2026 den TITELINHALT (nicht nur die Metadaten) einer
        Playlist nur noch fuer Playlists, die man selbst besitzt oder
        mitverwaltet - bei nur gespeicherten/gefolgten Playlists (z.B. von
        Spotify kuratierte oder fremde) kommt zwar ein Erfolg (200) zurueck,
        aber ohne Titel. Das Flag erlaubt dem Interface, das vorab klar zu
        kommunizieren statt nur stumm "keine Titel" zu zeigen."""
        if self._user_playlists_cache is not None:
            return self._user_playlists_cache

        current_user_id = self._get_current_user_id()
        playlists = []
        offset = 0
        page = 0
        while True:
            if page > 0:
                time.sleep(0.15)
            raw = self.sp.current_user_playlists(limit=10, offset=offset)
            batch = raw.get("items", [])
            playlists.extend(batch)
            page += 1
            if not batch or not raw.get("next"):
                break
            offset += raw.get("limit") or len(batch)
            if offset > 200:  # Sicherheitsnetz
                break

        results = []
        for p in playlists:
            # Spotify liefert gelegentlich "null" fuer Playlists, die nicht
            # mehr verfuegbar sind (z.B. vom Ersteller geloescht) - ueberspringen.
            if not p or not p.get("id"):
                continue
            images = p.get("images") or []
            owner_id = (p.get("owner") or {}).get("id")
            # Spotify hat das Zusammenfassungs-Feld fuer die Titelanzahl im
            # Rahmen der Februar-2026-Aenderungen von "tracks" auf "items"
            # umbenannt (undokumentiert, gleiches Muster wie beim einzelnen
            # Playlist-Eintrag) - beide Varianten pruefen, und sowohl den
            # Fall eines Zusammenfassungs-Objekts ({"total": N}) als auch
            # einer direkten Liste abdecken.
            tracks_summary = p.get("tracks")
            if tracks_summary is None:
                tracks_summary = p.get("items")
            if isinstance(tracks_summary, dict):
                track_count = tracks_summary.get("total", 0)
            elif isinstance(tracks_summary, list):
                track_count = len(tracks_summary)
            else:
                track_count = 0
            results.append({
                "id": p["id"],
                "name": p.get("name") or "(ohne Namen)",
                "cover": images[0]["url"] if images else None,
                "track_count": track_count,
                "owned": owner_id == current_user_id,
            })
        self._user_playlists_cache = results
        return results

    def get_playlist_tracks(self, playlist_id):
        """Titel einer Playlist, paginiert (limit=10, siehe get_user_playlists).
        Lokale Dateien/entfernte Titel (kein Track-Objekt) werden
        uebersprungen, der Content-Creator-Filter wird ebenfalls angewendet.
        Nutzt bewusst die Standard-Antwortstruktur von spotipy (kein
        explizites `fields`-Muster) - das ist die nachweislich
        funktionierende Variante.

        Wichtig: Seit Spotifys Aenderungen im Februar 2026 heisst das Feld
        mit dem eigentlichen Titel in jedem Playlist-Eintrag "item" statt
        wie zuvor "track" (undokumentiert - siehe Chat-Verlauf). Es wird
        deshalb zuerst "item", dann als Fallback "track" geprueft.

        Wird EINMAL pro Playlist gecacht (siehe _playlist_tracks_cache) -
        sonst wuerde jeder erneute Klick auf dieselbe Playlist die komplette
        Titelliste nochmal abfragen. Zusaetzlich eine kleine Pause zwischen
        den Seiten-Anfragen gegen Kurzzeit-Burst-Limits, und eine deutlich
        niedrigere Sicherheitsgrenze als frueher (max. 300 statt 2000 Titel)
        - bei sehr grossen Playlists (z.B. eine umfangreiche "Lieblings-
        songs"-Sammlung) waeren sonst leicht 100+ Anfragen in Folge noetig
        gewesen, was Spotifys Rate-Limit ausloesen kann.

        Wichtig: Die Paginierung verlaesst sich NICHT darauf, ob eine Seite
        kuerzer als das angefragte limit=10 ist (das haette bedeutet:
        "Ende erreicht") - Spotify liefert bei diesem Endpunkt in der Praxis
        teils weniger pro Seite als angefragt (z.B. nur 5), unabhaengig vom
        angeforderten limit. Stattdessen wird Spotifys eigenes "next"-Feld
        geprueft (zeigt zuverlaessig an, ob es eine weitere Seite gibt) und
        mit dem tatsaechlich zurueckgegebenen limit weitergeblaettert."""
        if playlist_id in self._playlist_tracks_cache:
            return self._playlist_tracks_cache[playlist_id]

        items = []
        offset = 0
        page = 0
        while True:
            if page > 0:
                time.sleep(0.15)
            raw = self.sp.playlist_items(
                playlist_id, limit=10, offset=offset, additional_types=("track",),
            )
            batch = raw.get("items", [])
            items.extend(batch)
            page += 1
            if not batch or not raw.get("next"):
                break
            offset += raw.get("limit") or len(batch)
            if offset > 300:  # Sicherheitsnetz - deutlich niedriger als frueher
                break

        results = []
        for it in items:
            # Spotify hat das Feld im Rahmen der Februar-2026-Aenderungen
            # von "track" auf "item" umbenannt (undokumentiert, siehe
            # Chat-Verlauf) - beide Varianten pruefen, damit es unabhaengig
            # von der tatsaechlich verwendeten Struktur funktioniert.
            track = (it or {}).get("item") or (it or {}).get("track")
            if not track or not track.get("uri"):
                continue  # z.B. lokale Datei oder entfernter/nicht verfuegbarer Titel
            artist_names = [a.get("name", "") for a in (track.get("artists") or [])]
            if self._is_excluded([track.get("name", ""), *artist_names]):
                continue
            album = track.get("album") or {}
            images = album.get("images") or []
            results.append({
                "uri": track["uri"],
                "name": track.get("name", "Unbekannter Titel"),
                "artist": ", ".join(a for a in artist_names if a),
                "album_cover": images[0]["url"] if images else None,
            })
        self._playlist_tracks_cache[playlist_id] = results
        return results

    def add_track_to_playlist(self, playlist_id, track_uri):
        self.sp.playlist_add_items(playlist_id, [track_uri])
        # Der Playlist-Cache ist damit veraltet (der neue Titel fehlt darin) -
        # verwerfen, damit ein erneuter Aufruf die aktuelle Liste zeigt.
        self._playlist_tracks_cache.pop(playlist_id, None)
