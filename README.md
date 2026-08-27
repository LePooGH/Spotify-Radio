# Spotify-Radio – Software-Vorbau (Ubuntu)

Software-Unterbau fuer das DIY-Spotify-Radio (Pi + HiFiBerry Amp2 + Touch
Display 2 + Drehencoder). Laeuft schon jetzt komplett auf einem
Ubuntu-Laptop und laesst sich unveraendert auf den Raspberry Pi umziehen,
sobald die Hardware da ist.

## Setup (Ubuntu)

1. Systempaket fuer die Wiedergabe installieren:
   ```
   sudo apt update && sudo apt install mpv
   ```

2. Projekt vorbereiten:
   ```
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. Konfiguration anlegen:
   ```
   cp .env.example .env
   ```
   `.env` oeffnen und `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` eintragen.
   Registrierung unter https://developer.spotify.com/dashboard, dort als
   Redirect-URI exakt `http://127.0.0.1:5000/callback` eintragen.

4. Starten:
   ```
   python app.py
   ```

5. Im Browser `http://127.0.0.1:5000` oeffnen und ueber den Banner oben
   einmalig mit Spotify verbinden (OAuth-Login).

## Wichtig fuer den Spotify-Teil

Damit "Play" wirklich Musik abspielt, braucht Spotify Connect ein aktives
Ziel-Geraet. Auf dem Laptop kannst du dafuer z.B. die normale Spotify-App
auf deinem Handy offen lassen und `SPOTIFY_DEVICE_NAME` in der `.env` auf
den Namen dieses Geraets setzen. Auf dem Pi uebernimmt spaeter raspotify
diese Rolle dauerhaft.

**Wichtig nach diesem Update:** Es werden jetzt zusaetzliche Spotify-Berechtigungen
gebraucht (Playlists lesen/bearbeiten). Der bisherige `.spotify_cache`
reicht dafuer nicht mehr aus - beim naechsten Start einmalig ueber den Banner
neu mit Spotify verbinden, dann fragt Spotify automatisch auch nach den neuen
Berechtigungen.

## Eigene Playlists, Wiederholen/Zufall, zu Playlist hinzufuegen

Über der Suchleiste sitzen rechtsbündig zwei Unter-Reiter zum Umschalten
zwischen "Alben" und "Playlists" in der linken Alben-Spalte. Playlists
werden dabei genauso dargestellt wie Alben (Cover mit Play-Button,
Aufklapp-Pfeil). Ein Klick auf das Cover spielt die Playlist sofort ab UND
zeigt sie rechts an, der Pfeil zeigt sie nur rechts an, ohne etwas
abzuspielen (zum reinen Durchstöbern). Die Überschrift der rechten Spalte
wechselt dabei passend zwischen "Aktuelles Album" und "Aktuelle Playlist".
Diese Ansicht bleibt "angepinnt" (wird nicht vom Status-Poll überschrieben),
bis eine andere Playlist ausgewählt oder die Quelle gewechselt wird.

Wird ein Album aus den Suchergebnissen abgespielt (Klick aufs Cover),
springt der Umschalter automatisch zurück auf "Alben" und die rechte Spalte
zurück auf "Aktuelles Album" - so bleibt die Anzeige konsistent, auch wenn
vorher eine Playlist "angepinnt" war. Das abgespielte Album bzw. die
abgespielte Playlist bekommt zusätzlich einen dünnen grünen Rahmen in der
jeweiligen Ergebnisliste, damit auf einen Blick erkennbar ist, was gerade
läuft - dabei ist immer nur eine Markierung gleichzeitig aktiv (Album ODER
Playlist), da ja auch nur eins von beidem wirklich spielen kann.

**Playlist-Titel wurden zwischenzeitlich nicht angezeigt, obwohl Spotify sie
korrekt lieferte:** Die Ursache war gefunden (siehe Chat-Verlauf) - Spotify
hat im Rahmen der Februar-2026-Änderungen das Feld mit dem eigentlichen
Titel in jedem Playlist-Eintrag undokumentiert von `"track"` auf `"item"`
umbenannt. Der Code prüft jetzt beide Varianten (`"item"` zuerst, `"track"`
als Fallback), damit es unabhängig von der tatsächlich verwendeten Struktur
funktioniert.

**Falls Playlist-Titel trotzdem nicht laden, obwohl die Playlists selbst
angezeigt werden:** Zwei weitere mögliche Ursachen, in dieser Reihenfolge
prüfen:

1. **Login-Berechtigung:** Lösche `.spotify_cache` und verbinde dich im
   Browser neu, damit sicher ein Token mit den neuen Playlist-Berechtigungen
   ausgestellt wird (ein bereits bestehender, "gültiger" Token wird sonst
   nicht automatisch ersetzt, auch wenn der Banner nicht erneut erscheint).
2. **Gespeicherte statt eigene Playlist:** Spotify liefert seit Februar 2026
   den **Titelinhalt** einer Playlist nur noch für Playlists, die man selbst
   erstellt hat oder mitverwaltet - bei nur gespeicherten/gefolgten
   Playlists (z.B. von Spotify kuratierte oder fremde) kommt zwar ein
   Erfolg (200) zurück, aber ohne Titel. Das Interface kennzeichnet solche
   Playlists jetzt in der Liste ("gespeichert (keine Titelanzeige möglich)")
   und zeigt beim Anklicken eine klare Erklärung statt nur "keine Titel
   gefunden". Betrifft nur die Titel-Anzeige/Auswahl - Abspielen der ganzen
   Playlist funktioniert unabhängig davon weiterhin.

**Wichtig gegen erneute Rate-Limit-Sperren:** Eigene Playlists und deren
Titel werden jetzt jeweils **einmal pro Sitzung gecacht** (nicht bei jedem
Klick neu abgefragt), mit kleinen Pausen zwischen den Seiten-Anfragen und
einer auf 300 Titel begrenzten Sicherheitsgrenze pro Playlist. Vorher hätte
das Anzeigen einer sehr grossen Playlist (z.B. eine umfangreiche
"Lieblingssongs"-Sammlung) bei jedem erneuten Klick erneut bis zu 100+
Anfragen ohne Pause ausgelöst - ein wahrscheinlicherer Ausloeser fuer
Rate-Limit-Sperren als die Diskografie-Suche.

🔀 (Zufällige Wiedergabe) und 🔁 (Wiederholen) sitzen rechts neben dem
"Weiter"-Button in der Transport-Zeile, sobald Spotify die aktive Quelle
ist. Wiederholen schaltet zyklisch: aus → Playlist/Album wiederholen (🔁) →
Titel wiederholen (🔂) → aus.

Jeder Titel (in der Suche, im aktuellen Album, in einer Playlist-Ansicht) hat
einen ➕-Button, der eine Auswahl der eigenen Playlists zum Hinzufuegen
oeffnet.

## Titel-Suche: "Meistgehörte Songs"

Spotify hat im Februar 2026 sowohl das `popularity`-Feld als auch den
"Get Artist's Top Tracks"-Endpunkt für Development-Mode-Apps entfernt (echte
Popularitäts-/Chartdaten gibt's seither nur noch im "Extended Quota Mode",
der ein registriertes Unternehmen mit 250.000+ monatlich aktiven Nutzern
voraussetzt - für ein privates Projekt nicht erreichbar). Als bestmöglicher
Ersatz: Bei einem Interpreten-Treffer (z.B. "Michael Jackson") sucht das
Backend in dessen Diskografie nach einem offiziellen "Best Of"/"Greatest
Hits"-Kompilationsalbum (erkannt an Namensmustern wie "Greatest Hits",
"Best Of", "Number Ones", "Essential", "Anthology" - Liste erweiterbar in
`_BEST_OF_KEYWORDS` in `spotify_module.py`) und zeigt dessen Titelliste
(bis zu 40 Songs) in der Titel-Spalte. Gibt es mehrere Kandidaten, gewinnt
der mit den meisten Titeln. Findet sich keine passende Kompilation, fällt es
auf die normale, relevanzbasierte Titel-Suche zurück.

## Selbst-Update über GitHub

Ein kleiner Button oben im Rahmen ("⬆ Update verfügbar") erscheint
**nur**, wenn im konfigurierten GitHub-Repository tatsächlich eine neuere
Version vorliegt (Prüfung alle 5 Minuten). Antippen lädt die neueste
Version herunter und wendet sie an.

**Voraussetzung:** Der Projektordner muss ein Git-Repository mit einem
`origin`-Remote sein, der auf dein GitHub-Repository zeigt:

```bash
# Falls noch nicht geschehen - GitHub-Repository erstellen, dann:
git remote add origin https://github.com/<dein-name>/<dein-repo>.git
git branch -M main
git push -u origin main
```

`UPDATE_BRANCH` in der `.env` legt fest, von welchem Branch aktualisiert
wird (Standard: `main`).

**Was beim Update passiert:** `git fetch` + `git reset --hard` auf den
Stand des Remote-Branches (verwirft dabei etwaige lokale, nicht
committete Änderungen an versionierten Dateien - `.env` und andere
`.gitignore`-Einträge sind davon nicht betroffen), danach werden neue/
geänderte Python-Abhängigkeiten aus `requirements.txt` installiert.

**Neustart nach dem Update:** Die App beendet sich danach selbst - auf
dem Pi (mit `deploy/spotify-radio.service`, das `Restart=on-failure`
gesetzt hat) startet systemd sie automatisch mit dem neuen Code neu. Im
Dev-Modus (ohne systemd) musst du `python app.py` danach manuell neu
starten.

## Selbst-Update über GitHub

Liegt im konfigurierten GitHub-Repository (`origin`-Remote) ein neuerer
Commit vor als der lokale Stand, erscheint oben in der App automatisch ein
Update-Hinweis. Antippen installiert das Update direkt (`git fetch` +
`git reset --hard` auf den Remote-Branch, danach `pip install -r
requirements.txt` falls sich Abhängigkeiten geändert haben).

**Voraussetzung:** Der Projektordner muss ein Git-Repository mit
eingerichtetem `origin`-Remote sein (z.B. durch `git clone` beim
Einrichten, oder nachträglich `git remote add origin <repo-url>` wie im
Chat-Verlauf beschrieben) - ohne das erscheint einfach nie ein
Update-Hinweis, kein Fehler.

**Nach der Installation:** Die App beendet sich kurz danach selbst. Auf dem
Pi (systemd-Service mit `Restart=on-failure`, siehe `deploy/`) startet sie
sich dadurch automatisch mit dem neuen Code neu. Im Dev-Modus ohne systemd
muss `python app.py` danach manuell neu gestartet werden.

**Wichtig:** `git reset --hard` verwirft dabei lokale, nicht committete
Änderungen an versionierten Dateien - nicht versionierte Dateien wie `.env`
(siehe `.gitignore`) sind davon nicht betroffen und bleiben erhalten.

Die Prüfung läuft automatisch alle 5 Minuten im Hintergrund (eigenes,
selteneres Intervall als der normale 2-Sekunden-Status-Poll, da eine echte
Netzwerkanfrage an GitHub involviert ist).

## Zuletzt gespielter Titel wird gemerkt

Der zuletzt gespielte Titel (inkl. Album, Cover, Interpret) wird in
`.last_played.json` zwischengespeichert - aktualisiert automatisch bei
jedem Titelwechsel während der Wiedergabe. Nach einem App-Neustart zeigt
"Aktuelles Album" diesen Titel direkt an (auch ohne dass gerade etwas
läuft), damit man sieht, was ein Druck auf ▶ fortsetzen würde. Es wird
**nicht** automatisch losgespielt - das Radio wartet auf den manuellen
Play-Druck.

## Wichtig: Spotifys Rate-Limit für Development-Mode-Apps

Private Spotify-Apps wie diese haben ein begrenztes Anfragenkontingent. Wird
es überschritten, blockiert Spotify die App teils für **mehrere Stunden bis
knapp 24 Stunden** (nicht nur ein paar Sekunden wie früher üblich) - das
merkt man z.B. an einer Fehlermeldung wie "Your application has reached a
rate/request limit". Dagegen hilft nur warten, es lässt sich nicht umgehen.

Um das zu vermeiden, ist die Diskografie-/Best-Of-Logik bewusst sparsam mit
Anfragen: Ein Interpreten-Katalog wird nur **einmal pro Interpret pro
laufender App-Sitzung** geladen und für Alben-Spalte UND Best-Of-Suche
gemeinsam genutzt (nicht zweimal separat), die Interpreten-Erkennung wird
pro Suchbegriff gecacht. Die Katalog-Tiefe ist auf `_CATALOG_MAX_PAGES`
(Standard: 50 Seiten = 500 Einträge, siehe `spotify_module.py`) begrenzt -
grosszügig genug, um auch sehr umfangreiche Diskografien (z.B. jahrzehnte-
lange Hörspielserien) komplett zu erfassen, mit einer kleinen Pause
zwischen den Seiten-Anfragen, um Kurzzeit-Burst-Limits nicht zu triggern.
Eine komplette Suche wie "Michael Jackson" braucht dadurch nur noch ca.
5-10 Spotify-Anfragen statt vorher 40-50+; ein einmaliger Tiefen-Crawl einer
sehr umfangreichen Diskografie (z.B. 24 Anfragen für 237 Einträge) passiert
dank Zwischenspeicherung nur beim ersten Aufruf pro Interpret, nicht bei
jeder erneuten Suche oder beim Scrollen.

### Vorab-Suche für umfangreiche Diskografien ("Hörspiele"-Reiter)

**"Hörspiele" ist der Standard-Reiter** (ganz links) im Spotify-Bereich,
daneben "Playlists" und ganz rechts **"Spotify"** (die normale, direkte
Albensuche - vormals "Alben" genannt, umbenannt weil darüber allgemein in
Spotify gesucht wird, nicht nur nach Alben). Für sehr umfangreiche Serien
(z.B. "Die drei ???" mit 200+ Folgen) spart der "Hörspiele"-Ablauf
Spotify-Anfragen fast komplett:

1. Die Suche fragt zuerst eine **externe, praktisch unlimitierte Datenbank**
   ab (iTunes Search API - kostenlos, kein Schlüssel nötig, deckt auch
   Hörbücher/Hörspiele ab) - **keine** Spotify-Anfrage nötig
2. Ergebnisse (Titel, Interpret, Erscheinungsjahr, Cover) werden angezeigt
3. Erst wenn ein **konkretes** Ergebnis angeklickt wird, startet eine
   **einzelne, gezielte** Spotify-Suche nur dafür (`search_album_by_hint`)
   - kein kompletter Katalog-Crawl mehr nötig
4. Episoden-/Folgen-Nummerierungen werden vor der Spotify-Suche entfernt
   (z.B. "Folge 100: Der Superpapagei" → "Der Superpapagei"), da diese
   zwischen den Quellen oft unterschiedlich formatiert sind - ein kürzerer,
   markanter Suchbegriff findet zuverlässiger den richtigen Treffer als der
   exakte, vollständige Titel

Die Titel-Spalte ist in diesem Modus bewusst deaktiviert, da die normale
Best-Of-Titelsuche intern dieselbe teure Katalog-Crawl-Logik nutzt, die
dieser Modus ja gerade vermeiden soll.

**Ehrlicher Hinweis:** Die Titel-Übereinstimmung zwischen der externen
Quelle und Spotify ist nicht zu 100% garantiert (leicht unterschiedliche
Schreibweisen sind möglich) - meistens findet die gezielte Suche trotzdem
den richtigen Treffer, aber gelegentlich kann "nicht gefunden" vorkommen,
dann hilft nur die normale Suche im "Alben"-Reiter.

Falls dir das Kontingent trotzdem mal ausgeht: einfach in Ruhe abwarten,
alle Caches liegen im Arbeitsspeicher der laufenden App und gehen bei einem
Neustart verloren, sammeln sich danach aber wieder von selbst.

## Web-Radio: Sender-Gruppierung

## Web-Radio: Aktueller Songtitel

Viele Internetradio-Streams senden eingebettete ICY-Metadaten ("Interpret -
Songtitel"), die sich periodisch aktualisieren. Diese werden jetzt über mpv
ausgelesen und im Dial-Display unterhalb des Sendernamens als
Rechts-nach-links-Lauftext angezeigt, mit sanftem Ein-/Ausblenden an den
Rändern. Nicht jeder Sender sendet diese Metadaten - fehlen sie, wird
stattdessen einfach nichts angezeigt (kein Fehler).

Die Lauftext-Geschwindigkeit ist auf eine konstante Pixel/Sekunde-Rate
festgelegt (`MARQUEE_SPEED_PX_PER_SEC` in `app.js`, Standard: 100px/s) statt
einer festen Zeit für alle Texte - dadurch laufen kurze Titel zügig durch
und lange Titel trotzdem garantiert komplett, bevor die Animation von vorne
beginnt (die tatsächliche Text- und Fensterbreite wird dafür per JavaScript
gemessen).

**Bekannte Grenze - Werbetext/Ticker-Infos im Titel:** Manche Sender packen
Zusatzinfos (Hotline-Nummern, Sport-Ticker etc.) mit in dasselbe
Metadaten-Feld wie den Songtitel, ohne sauber getrennte Felder. Eine
Heuristik in `player.py` (`_clean_song_title`) versucht, bekannte Muster
(Hotline-Nummern, Ticker-Zahlen wie "2 zu 1") herauszufiltern und nur den
Bereich um das letzte "Interpret - Titel"-Muster zu behalten - das
funktioniert nicht bei jedem Sender perfekt, da sich freier Ticker-Text
generisch nicht immer zuverlässig von einem Interpretennamen unterscheiden
lässt.

Radio-Browser listet denselben Sender oft mehrfach (z.B. "Deutschlandfunk"
als AAC 48k/96k/192k und MP3 128k/256k sowie zusätzlich als "DLF"). Diese
Varianten werden jetzt automatisch zu **einer** Sender-Zeile zusammengefasst
(erkannt am Namen nach Entfernen von Codec-/Bitrate-Zusätzen sowie über die
`ABBREVIATIONS`-Zuordnung, damit z.B. "DLF" mit "Deutschlandfunk" verschmilzt)
- als Anzeigename gewinnt der in den Rohtreffern häufigste Name.

Bedienung wie bei den Spotify-Alben/USB-Ordnern: Klick auf das Sender-Icon
spielt automatisch die beste verfügbare Qualität, der Pfeil rechts klappt
bei mehreren Varianten eine Liste zur Feinauswahl auf (z.B. gezielt eine
niedrigere Bitrate bei schlechter Internetverbindung). Da intern deutlich
mehr Rohtreffer abgefragt werden, bevor gruppiert wird, tauchen jetzt auch
verwandte Sender wie "Deutschlandfunk Kultur" oder "Deutschlandfunk Nova"
zuverlässig mit auf, statt von Bitrate-Duplikaten des Hauptsenders verdrängt
zu werden.

**Automatischer Server-Fallback:** Radio-Browser besteht aus mehreren
unabhängigen Spiegel-Servern, die sich untereinander synchronisieren -
gelegentlich ist einer davon kurzzeitig langsam oder noch nicht ganz
synchron und meldet fälschlich "keine Treffer". Liefert der erste Server
(`de1`) eine leere Antwort oder einen Fehler/Timeout, wird automatisch der
nächste (`de2`, dann `at1`) probiert, bevor wirklich "keine Treffer"
zurückgegeben wird - Liste der Server in `RADIO_BROWSER_HOSTS` in
`webradio_module.py`.

**Saubere Anzeigenamen bei zusammengesetzten Sendernamen:** Manche
Radio-Browser-Einträge tragen den kompletten Namen als einen
zusammengesetzten String ein (z.B. "Deutschlandfunk | DLF | AAC 192" statt
sauber getrennter Felder). Für Gruppierung und Anzeige wird jetzt nur der
Teil vor dem ersten "|" als eigentlicher Sendername verwendet - "DLF | AAC
192"-Varianten fallen dadurch korrekt mit plainem "Deutschlandfunk" in eine
Gruppe, und der Anzeigename ist "Deutschlandfunk" statt des hässlichen
zusammengesetzten Strings.

**Bekannte Grenze - falsche Bitrate-Angaben:** Die Varianten-Labels (z.B.
"AAC 192k") stammen direkt aus Radio-Browsers eigenen `codec`-/`bitrate`-
Feldern. Diese werden von den Sender-Betreibern selbst gepflegt und sind
gelegentlich veraltet oder falsch (z.B. steht dort "192k", obwohl der Stream
tatsächlich mit 256k läuft) - das lässt sich von hier aus nicht korrigieren,
da wir keine Möglichkeit haben, die tatsächliche Bitrate eines Streams ohne
aufwändiges Live-Probing zu verifizieren. Die Wiedergabe selbst ist davon
nicht betroffen - es spielt immer die tatsächliche Stream-Qualität ab,
unabhängig davon, was das Label behauptet.

## Suchfilter anpassen

Die Spotify-Suche (Titel und Alben, gleichzeitig in zwei Spalten) blendet
Ergebnisse aus, die auf Content-Creator-Inhalte hindeuten (z.B. Gaming-
YouTuber-Tracks, GTA-/Brawl-Stars-Bezüge, TikTok-Sounds). Die Liste der
Schlüsselwörter und gezielt auszuschliessender Interpreten (aktuell z.B.
"LukasBS") steht in `config.py` (`SEARCH_EXCLUDED_KEYWORDS` /
`SEARCH_EXCLUDED_ARTISTS`) und lässt sich dort einfach erweitern, ohne Code
in `modules/spotify_module.py` anfassen zu müssen. Es gibt keine seriöse,
vorgefertigte "Liste aller Content Creator" - die Liste wächst am besten mit,
sobald dir weitere Namen auffallen.

Sucht man direkt nach einem gesperrten Begriff selbst (z.B. "LukasBS" oder
"GTA 5" statt nur einem Song, der zufällig einen dieser Begriffe enthält),
erscheint statt einer stillen Leerliste ein deutlicher roter Warnhinweis
("🚫 Dieser Suchbegriff ist gesperrt.") in beiden Spalten.

Jede Suche zeigt Titel und Alben parallel in zwei unabhängig scrollbaren
Spalten (kein Umschalten nötig). Alben erscheinen neueste zuerst: Wenn die
Suchanfrage einem Interpreten zugeordnet werden kann (z.B. "Die drei ???"),
wird dessen echte, vollständige Diskografie über die Spotify-Artist-API
geladen - dabei werden ALLE Seiten auf einmal abgerufen, dedupliziert und
als Ganzes sortiert (dreistufiges Schema: Nummer-Titel wie "264/..." zuerst,
dann "FolgeXX"-Titel, dann Rest alphabetisch - alle Nummern-Gruppen
absteigend). Das Ergebnis wird pro Interpret zwischengespeichert, damit die
Sortierung auch beim Nachladen (Infinite Scroll) nahtlos bleibt - würde man
nur einzelne 10er-Häppchen für sich sortieren, könnten beim Weiterscrollen
scheinbar "falsche" Alben zwischen den eigentlich zusammengehörigen
auftauchen, weil Spotify pro Anfrage ohnehin nur maximal 10 Treffer liefert
(Stand Februar 2026).

Jede Album-Zeile in der Suche hat zwei getrennte Aktionen: ein Klick auf das
Cover (mit kleinem Play-Symbol) spielt das ganze Album sofort ab, ein Klick
auf den Pfeil rechts klappt stattdessen die Titelliste direkt in der Suche
auf (nochmaliger Klick klappt sie wieder ein) - ohne dass dabei etwas
abgespielt wird.

Rechts neben der Bedienung zeigt eine eigene Spalte "Aktuelles Album" immer
das Album des gerade laufenden Titels inkl. kompletter Titelliste an, der
aktuell spielende Titel ist darin hervorgehoben. Diese Spalte aktualisiert
sich automatisch mit dem Wiedergabe-Status.

## USB-Sticks

Das USB-Modul sucht selbststaendig nach eingehaengten Datentraegern unter
`/media/<user>` und `/run/media/<user>` (dort haengt Linux Wechseldatentraeger
ueblicherweise automatisch ein - auf dem Ubuntu-Laptop erledigt das die
Desktop-Umgebung von selbst, auf dem Pi braucht es dafuer spaeter noch eine
udisks2-Einrichtung). Zusaetzlich zaehlt im Dev-Modus der Ordner `sample_usb/`
als virtueller Stick.

- Ist genau ein Stick mit MP3-Inhalt gefunden, wird er automatisch benutzt
- Sind mehrere gefunden, zeigt das Interface eine Auswahlliste
- Leere Sticks (ohne Audiodateien) werden ignoriert
- Die Titelliste wird nach Dateiname sortiert (natürliche Sortierung: "Track
  9" kommt vor "Track 10", nicht danach wie bei reinem Textvergleich) - nicht
  nach dem angezeigten Titel, da ID3-Tags fehlen oder fehlerhaft sein können
- Bekannte System-/Papierkorb-Ordner (`$RECYCLE.BIN`, `System Volume
  Information` u.ä.) sowie versteckte Dateien (z.B. macOS-Ressourcendateien
  wie `._Song.mp3`, die entstehen, sobald der Stick mal an einem Mac
  angeschlossen war) werden automatisch übersprungen
- Fehlen brauchbare ID3-Tags, wird als Titel der bereinigte Dateiname
  angezeigt (Endung weg, Unterstriche durch Leerzeichen ersetzt) statt des
  rohen Dateinamens
- Enthält ein ID3-Tag verdächtige Zeichen, die auf einen beschädigten/
  fehlerhaft kodierten Tag hindeuten (z.B. Rückwärtsschrägstrich, Backtick,
  geschweifte Klammern - kommt in echten Titeln praktisch nie vor), wird der
  Tag verworfen und stattdessen der Dateiname verwendet

### Ordner wie Alben

Enthält der Stick mehrere Ordner mit MP3-Dateien, werden diese wie
Spotify-Alben angezeigt (Cover-Symbol mit Play-Button, Aufklapp-Pfeil für die
Titelliste direkt in der Suche) - Klick auf das Ordner-Symbol spielt den
ersten Titel des Ordners, Klick auf den Pfeil klappt die Titelliste auf.

- **Mehrere Ordner mit MP3s:** werden als Alben-Liste angezeigt
- **Genau ein Ordner mit MP3s:** wird direkt in der rechten Spalte gezeigt,
  die dafür den Namen des Ordners als Überschrift erhält (kein zusätzlicher
  Klick nötig)
- **Keine Unterordner** (Dateien liegen direkt im Wurzelverzeichnis): auch
  hier zeigt die rechte Spalte den Inhalt an, die Überschrift ist dann der
  Name des USB-Sticks selbst

## Umzug auf den Raspberry Pi

Sobald die Teile da sind:

1. Projektordner auf den Pi kopieren (z.B. per `git` oder `scp`)
2. raspotify installieren (macht den Pi zum Spotify-Connect-Ziel)
3. In der `.env`: `PLATFORM=pi` setzen, `SPOTIFY_DEVICE_NAME` auf den
   Pi-Hostnamen anpassen
4. `pip install gpiozero lgpio` (nur auf dem Pi noetig)
5. App wie gewohnt starten – die Drehencoder-Steuerung aktiviert sich
   automatisch, das Web-Interface laeuft dann im Chromium-Kiosk-Modus auf
   dem Touchdisplay

Am Code selbst muss dafuer nichts geaendert werden – das war der Sinn der
`PLATFORM`-Umschaltung in `config.py` / `modules/input_controller.py`.

### Sicheres Herunterfahren per Aus-Knopf

Ein physischer Taster (`modules/shutdown_button.py`) fährt den Pi sauber
herunter, statt dass man einfach den Stecker zieht - schützt die SD-Karte
vor Beschädigung durch abrupten Stromverlust. **3 Sekunden gedrückt
halten** (nicht nur kurz antippen) löst das Herunterfahren aus, damit man
den Pi nicht aus Versehen mitten im Hören abschaltet.

**Verkabelung:** Taster zwischen **GPIO 26** (Standard, in der `.env` über
`SHUTDOWN_BUTTON_PIN` änderbar) und einem GND-Pin. Bitte vor dem Anschließen
kurz prüfen, dass GPIO 26 bei eurem konkreten Aufbau (Amp2 + Touchdisplay)
wirklich frei ist - das kann ich ohne Sicht auf die tatsächliche Verkabelung
nicht zusichern.

**Einmalige Einrichtung auf dem Pi (zwingend nötig, sonst schlägt das
Herunterfahren fehl):** Das Skript läuft nicht interaktiv und kann deshalb
keine Passwort-Abfrage beantworten - `sudo shutdown` muss daher einmalig
ohne Passwort erlaubt werden:
```bash
sudo visudo -f /etc/sudoers.d/spotty-shutdown
```
Dort folgende Zeile eintragen (`<BENUTZER>` durch euren tatsächlichen
Benutzernamen ersetzen):
```
<BENUTZER> ALL=(ALL) NOPASSWD: /sbin/shutdown
```
Speichern und schließen - das reicht, keine weiteren Schritte nötig.

**Ist noch kein Taster angeschlossen:** `SHUTDOWN_BUTTON_ENABLED=false` in
der `.env` setzen - verhindert, dass ein nicht verbundener, frei
schwebender GPIO-Pin versehentlich ein Herunterfahren auslöst.

## Projektstruktur

```
app.py                    Flask-Hauptanwendung, verbindet alle Module
config.py                 zentrale Konfiguration (liest .env)
modules/
  spotify_module.py       Spotify Web API (Suche nach Titeln/Alben, Geräteauswahl, Steuerung via spotipy)
  player.py               gemeinsamer mpv-Player fuer Web-Radio & USB
  webradio_module.py      Sendersuche (Radio-Browser-API) + Wiedergabe
  usb_module.py           Auflisten/Abspielen lokaler MP3-Dateien
  input_controller.py     Abstraktion fuer den Drehencoder (nur Pi)
templates/index.html      Touch-Oberflaeche
static/style.css          Retro-Radio-Optik
static/app.js             Frontend-Logik (Polling, Suche, Steuerung)
sample_usb/                Testordner fuer das USB-Modul im Dev-Modus
```

## Noch offen (bewusst nicht Teil dieses Grundgeruests)

- Wake-Word-Sprachsteuerung ("Spotty") – eigenes Modul, kommt spaeter dazu
- Bluetooth-Audio-Sink (fuer Apple Music, Amazon Music, Hoerspiel Player
  etc.) – ebenfalls ein spaeteres, separates Modul

### Erledigt: sauberer Quellenwechsel

Beim Wechsel der Quelle (`/api/source`) wird die bisherige Quelle jetzt
ueber `stop()` vollstaendig beendet statt nur pausiert (`_stop_current_source()`
in `app.py`). Bei Spotify bleibt `pause()` die richtige Wahl, da es dort keine
lokale Ressource zum Freigeben gibt. `MPVPlayer.stop()` startet dabei bewusst
keinen mpv-Prozess, falls ohnehin noch nichts lief.

Ein Punkt bleibt trotzdem als Hinweis fuer den Pi: Ob die ALSA-Audio-Hardware
wirklich sofort freigegeben wird, haengt am Ende auch vom Treiber ab. Falls es
beim Wechsel zwischen Spotify (raspotify/librespot) und Web-Radio/USB (mpv) zu
"device busy"-Fehlern kommt, hilft eine gemeinsame ALSA-dmix- oder
PulseAudio/PipeWire-Konfiguration, die beiden Prozessen gleichzeitig Zugriff
erlaubt, statt sich auf exklusives Freigeben zu verlassen.
