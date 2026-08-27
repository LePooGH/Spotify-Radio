"""
Externe Diskografie-Suche (iTunes Search API) als Vorstufe zur eigentlichen
Spotify-Suche.

Der Grund: Bei sehr umfangreichen Diskografien (z.B. Hoerspielserien wie
"Die drei ???" mit 200+ Folgen) ist ein kompletter Spotify-Katalog-Crawl
teuer und riskiert Spotifys Rate-Limit fuer Development-Mode-Apps (siehe
Chat-Verlauf). Stattdessen wird zuerst eine externe, praktisch unlimitierte
Datenbank befragt (keine Spotify-Anfrage noetig) - erst wenn der Nutzer ein
KONKRETES Ergebnis daraus auswaehlt, startet eine einzelne, gezielte
Spotify-Suche nur dafuer (siehe SpotifyModule.search_album_by_hint).

iTunes Search API: kostenlos, kein API-Schluessel/keine Anmeldung noetig,
deckt sowohl Musik-Alben als auch Hoerbuecher/Hoerspiele ab (getrennte
Kategorien bei Apple, deshalb werden hier beide abgefragt).

WICHTIG (siehe Chat-Verlauf): Der einfache /search-Endpunkt ist
RELEVANZBASIERT, nicht vollstaendig - bei umfangreichen Serien liefert er
nur eine Stichprobe der "relevantesten" Treffer mit grossen Luecken (z.B.
Folge 1,2,3, dann ploetzlich 58,59,108,...). Deshalb wird hier zuerst nur
die Interpreten-ID ermittelt (_resolve_artist), und dann ueber den
separaten /lookup-Endpunkt (siehe _full_catalog_for_artist) der
TATSAECHLICH VOLLSTAENDIGE Katalog dieses Interpreten abgerufen - das
entspricht demselben Prinzip wie Spotifys artist_albums-Endpunkt, den wir
fuer die Spotify-eigene Diskografie-Anzeige nutzen. Nur wenn sich kein
Interpret eindeutig zuordnen laesst (z.B. bei einer sehr spezifischen
Einzeltitel-Suche), faellt der Code auf die normale Textsuche zurueck.
"""
import re

import requests

ITUNES_SEARCH_API = "https://itunes.apple.com/search"
ITUNES_LOOKUP_API = "https://itunes.apple.com/lookup"
# Von Apple dokumentierte Obergrenze - mehr liefert die API grundsaetzlich
# nicht zurueck, auch keine Seitennummerierung darueber hinaus.
ITUNES_MAX_LIMIT = 200

# Erkennt Episoden-/Folgen-Nummerierungen, die zwischen der externen Quelle
# und Spotify oft unterschiedlich formatiert sind (z.B. "Folge 100:" vs.
# "100 - " vs. "Teil 100"). Werden vor der Spotify-Suche entfernt, damit nur
# noch die markantesten, garantiert uebereinstimmenden Wörter uebrig bleiben
# (siehe Chat-Verlauf: kurze, robuste Suchbegriffe statt exaktem Titel).
_EPISODE_PATTERN_RE = re.compile(
    r"\b(folge|teil|episode|kapitel|nr\.?|track)\s*\.?\s*\d+\b\s*[:\-]?\s*",
    re.IGNORECASE,
)
_LEADING_NUMBER_RE = re.compile(r"^\s*\d+\s*[:\-.]?\s*")

# Wie _EPISODE_PATTERN_RE, aber mit einer Erfassungsgruppe fuer die Nummer
# selbst - wird fuers Sortieren gebraucht (siehe _extract_episode_number),
# nicht nur zum Erkennen/Entfernen wie oben.
_EPISODE_NUMBER_RE = re.compile(
    r"\b(?:folge|teil|episode|kapitel|nr\.?|track)\s*\.?\s*(\d+)\b",
    re.IGNORECASE,
)
_LEADING_NUMBER_CAPTURE_RE = re.compile(r"^\s*(\d+)\b")


class ExternalSearchModule:
    def search_albums(self, query, limit=25):
        """Sucht Alben/Hoerspiele in der externen Datenbank (iTunes).

        Versucht zuerst, den Suchbegriff einem KONKRETEN Interpreten
        zuzuordnen und dessen VOLLSTAENDIGEN Katalog per Lookup zu laden
        (siehe Modul-Docstring - vermeidet die Luecken der reinen
        Textsuche). Gelingt das nicht oder liefert keine Treffer, faellt
        der Code auf die normale (relevanzbasierte) Textsuche zurueck.

        Ergebnisse werden nach erkannter Folgen-/Episoden-Nummer sortiert
        zurueckgegeben (z.B. "Folge 1" vor "Folge 2" vor "Folge 100")."""
        artist_hint = self._resolve_artist(query)
        if artist_hint:
            results = self._full_catalog_for_artist(*artist_hint)
            if results:
                return results
        return self._search_by_term(query, limit)

    def _resolve_artist(self, query):
        """Ermittelt eine iTunes-Interpreten-ID zum Suchbegriff: eine kurze
        Textsuche (nur als Werkzeug zur Identifikation, nicht als
        Ergebnisquelle selbst) liefert Kandidaten - von deren Katalog wird
        anschliessend per Lookup (_full_catalog_for_artist) alles
        abgerufen, nicht nur der eine gefundene Treffer.

        WICHTIG (siehe Chat-Verlauf): Der erste Treffer wird NICHT blind
        uebernommen - iTunes' Suche kommt mit Sonderzeichen wie "???" nicht
        gut zurecht und kann dann einen voellig unpassenden ersten Treffer
        liefern (z.B. "Die drei ???" -> "Die Feriendetektive"). Ein
        Kandidat wird nur akzeptiert, wenn ALLE bedeutsamen Woerter aus dem
        Suchbegriff auch im Interpretennamen vorkommen - sonst wird der
        naechste Kandidat geprueft bzw. auf die normale Textsuche
        zurueckgefallen (_search_by_term), die zumindest keine komplett
        falsche Serie anzeigt."""
        query_tokens = set(re.findall(r"\w+", query.lower()))
        if not query_tokens:
            return None
        for media, entity in (("audiobook", "audiobook"), ("music", "album")):
            try:
                response = requests.get(
                    ITUNES_SEARCH_API,
                    params={"term": query, "media": media, "entity": entity, "limit": 10, "country": "DE"},
                    timeout=6,
                )
                response.raise_for_status()
                data = response.json()
            except (requests.RequestException, ValueError):
                continue
            for item in data.get("results", []):
                artist_id = item.get("artistId")
                artist_name = item.get("artistName") or ""
                if not artist_id:
                    continue
                artist_tokens = set(re.findall(r"\w+", artist_name.lower()))
                if query_tokens <= artist_tokens:  # ALLE Suchwoerter muessen vorkommen, nicht nur eins
                    return artist_id, entity
        return None

    def _full_catalog_for_artist(self, artist_id, entity):
        """Laedt per Lookup-Endpunkt (siehe Modul-Docstring) den kompletten
        Katalog eines KONKRETEN Interpreten - bis zu 200 Eintraege
        (Apples Obergrenze), im Gegensatz zur relevanzbasierten Textsuche
        eine tatsaechlich vollstaendige (bzw. bei sehr grossen Katalogen
        bestmoeglich vollstaendige) Liste."""
        try:
            response = requests.get(
                ITUNES_LOOKUP_API,
                params={"id": artist_id, "entity": entity, "limit": ITUNES_MAX_LIMIT, "country": "DE"},
                timeout=8,
            )
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, ValueError):
            return []

        results = []
        seen = set()
        for item in data.get("results", []):
            # Der erste Eintrag beim Lookup ist ueblicherweise der
            # Interpret selbst (wrapperType "artist"), kein Album/Hoerspiel
            # - der wird uebersprungen, nicht als Ergebnis gezaehlt.
            if item.get("wrapperType") == "artist":
                continue
            self._add_result(results, seen, item)

        results.sort(key=self._sort_key)
        for item in results:
            del item["_release_date"]
        return results

    def _search_by_term(self, query, limit):
        """Normale relevanzbasierte Textsuche - Rueckfall, falls sich kein
        Interpret eindeutig zuordnen liess (z.B. bei einer sehr
        spezifischen Einzeltitel-Suche statt einer Serien-/
        Interpretensuche)."""
        results = []
        seen = set()
        for media, entity in (("audiobook", "audiobook"), ("music", "album")):
            try:
                response = requests.get(
                    ITUNES_SEARCH_API,
                    params={
                        "term": query,
                        "media": media,
                        "entity": entity,
                        "limit": limit,
                        "country": "DE",
                    },
                    timeout=6,
                )
                response.raise_for_status()
                data = response.json()
            except (requests.RequestException, ValueError):
                continue
            for item in data.get("results", []):
                self._add_result(results, seen, item)

        results.sort(key=self._sort_key)
        for item in results:
            del item["_release_date"]
        return results

    def _add_result(self, results, seen, item):
        """Gemeinsame Formatierungs-/Dedupe-Logik fuer beide Wege (Lookup
        und Textsuche)."""
        title = item.get("collectionName") or ""
        artist = item.get("artistName") or ""
        if not title:
            return
        key = (title.lower(), artist.lower())
        if key in seen:
            return
        seen.add(key)
        cover = (item.get("artworkUrl100") or "").replace("100x100", "400x400")
        release_date = item.get("releaseDate") or ""
        results.append({
            "title": title,
            "artist": artist,
            "cover": cover or None,
            "release_year": release_date[:4] or None,
            "track_count": item.get("trackCount"),
            "_release_date": release_date,  # nur intern fuers Sortieren, siehe _sort_key
        })

    def _extract_episode_number(self, title):
        """Liest eine Folgen-/Episoden-Nummer aus einem Titel, z.B. 'Folge
        100: Der Superpapagei' -> 100. Gibt None zurueck, wenn keine
        erkennbare Nummerierung vorhanden ist (z.B. bei normalen
        Musik-Alben)."""
        match = _EPISODE_NUMBER_RE.search(title) or _LEADING_NUMBER_CAPTURE_RE.match(title)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    def _sort_key(self, item):
        episode_number = self._extract_episode_number(item["title"])
        if episode_number is not None:
            # Gruppe 0: hat eine erkennbare Nummer -> danach sortiert, kommt
            # vor allem ohne Nummer (Gruppe 1).
            return (0, episode_number, item["title"].lower())
        return (1, item.get("_release_date") or "9999", item["title"].lower())

    def simplify_title_for_search(self, title):
        """Entfernt Episoden-/Folgen-Nummerierungen aus einem externen Titel,
        damit die anschliessende Spotify-Suche nur noch mit den markantesten
        Woertern arbeitet - robuster gegen Formatierungsunterschiede
        zwischen den Quellen als der exakte, vollstaendige Titel."""
        cleaned = _EPISODE_PATTERN_RE.sub(" ", title)
        cleaned = _LEADING_NUMBER_RE.sub("", cleaned)
        cleaned = " ".join(cleaned.split())
        return cleaned or title
