const state = {
  source: "spotify",
  spotifyQuery: "",
  spotifyOffsets: { track: 0, album: 0 },
  spotifyExhausted: { track: false, album: false },
  spotifyLoading: { track: false, album: false },
  currentAlbumId: null,
  currentTrackUri: null,
  // "auto" = rechte Spalte folgt der Spotify-Wiedergabe automatisch,
  // "playlist"/"usb" = manuell "angepinnt", wird vom Status-Poll nicht
  // ueberschrieben (siehe updateCurrentAlbumPanel).
  rightPanelMode: "auto",
  currentPlaylistId: null,
  activeAlbumUri: null,
  activePlaylistId: null,
  usbActiveDevicePath: null,
  playlistsCache: null,
  shuffleOn: false,
  repeatMode: "off",
};

const els = {
  tabs: document.querySelectorAll(".tab"),
  panels: document.querySelectorAll(".source-panel"),
  cover: document.getElementById("now-cover"),
  title: document.getElementById("now-title"),
  subtitle: document.getElementById("now-subtitle"),
  playPause: document.getElementById("btn-playpause"),
  prev: document.getElementById("btn-prev"),
  next: document.getElementById("btn-next"),
  volume: document.getElementById("volume-slider"),
  spotifyForm: document.getElementById("spotify-search-form"),
  spotifyInput: document.getElementById("spotify-search-input"),
  trackResults: document.getElementById("spotify-track-results"),
  albumResults: document.getElementById("spotify-album-results"),
  playlistsList: document.getElementById("spotify-playlists"),
  onlineResults: document.getElementById("spotify-online-results"),
  albumSubtabs: document.querySelectorAll("#panel-spotify .subtab"),
  radioForm: document.getElementById("radio-search-form"),
  radioInput: document.getElementById("radio-search-input"),
  radioResults: document.getElementById("radio-results"),
  usbRefresh: document.getElementById("usb-refresh"),
  usbEject: document.getElementById("usb-eject"),
  usbDevices: document.getElementById("usb-devices"),
  usbResults: document.getElementById("usb-results"),
  deviceToggle: document.getElementById("device-toggle"),
  deviceList: document.getElementById("device-list"),
  currentAlbumCover: document.getElementById("current-album-cover"),
  currentAlbumName: document.getElementById("current-album-name"),
  currentAlbumArtist: document.getElementById("current-album-artist"),
  currentAlbumTracks: document.getElementById("current-album-tracks"),
  playbackModes: document.getElementById("playback-modes"),
  btnShuffle: document.getElementById("btn-shuffle"),
  btnRepeat: document.getElementById("btn-repeat"),
};

async function switchSource(source) {
  state.source = source;
  // Beim Wechsel der Quelle die "Anpinnung" der rechten Spalte zuruecksetzen:
  // USB verwaltet sie selbst, bei allen anderen folgt sie automatisch der
  // Wiedergabe (eine zuvor ausgewaehlte Playlist wird dabei bewusst nicht
  // "gemerkt" - einfacher und vorhersehbarer, als sie ueber Tab-Wechsel
  // hinweg zu erhalten).
  state.rightPanelMode = source === "usb" ? "usb" : "auto";
  els.tabs.forEach((t) => t.classList.toggle("active", t.dataset.source === source));
  els.panels.forEach((p) => p.classList.toggle("active", p.id === `panel-${source}`));
  // Sofort lokal ausblenden fuers erste visuelle Feedback...
  els.playbackModes.hidden = source !== "spotify";
  // ...UND auf die Server-Antwort warten, BEVOR der Status abgefragt wird -
  // sonst kann refreshStatus() den Server noch mit der alten Quelle
  // erwischen (Race Condition) und die Buttons direkt wieder einblenden.
  await fetch("/api/source", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source }),
  });
  if (source === "usb") loadUsbList();
  refreshStatus();
}

els.tabs.forEach((tab) => tab.addEventListener("click", () => switchSource(tab.dataset.source)));

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

let lastMarqueeText = null;
let currentMarqueeAnimation = null;

// Konstante Geschwindigkeit in Pixel/Sekunde statt fester Zeit fuer alle
// Textlaengen - dadurch laufen kurze Titel zuegig und lange Titel trotzdem
// garantiert komplett durch, bevor die Animation von vorne beginnt.
const MARQUEE_SPEED_PX_PER_SEC = 50;

function startMarqueeAnimation() {
  const span = els.subtitle.querySelector(".marquee-text");
  if (!span) return;
  if (currentMarqueeAnimation) currentMarqueeAnimation.cancel();

  const containerWidth = els.subtitle.clientWidth;
  const textWidth = span.scrollWidth;
  // Weg: von komplett rechts ausserhalb (containerWidth) bis komplett
  // links ausserhalb (-textWidth) - das ist die exakte Distanz, die noetig
  // ist, damit der GESAMTE Text sichtbar durchlaeuft, unabhaengig von
  // seiner Laenge.
  const distance = containerWidth + textWidth;
  const duration = Math.max((distance / MARQUEE_SPEED_PX_PER_SEC) * 1000, 2500);

  currentMarqueeAnimation = span.animate(
    [
      { transform: `translateX(${containerWidth}px)` },
      { transform: `translateX(${-textWidth}px)` },
    ],
    { duration, iterations: Infinity, easing: "linear" }
  );
}

function setSubtitle(text, scrolling) {
  if (scrolling && text) {
    // Nur neu aufbauen (und damit die Lauftext-Animation neu starten), wenn
    // sich der Text wirklich geaendert hat - sonst wuerde jeder
    // Status-Poll (alle 2 Sekunden) die Animation vorzeitig zuruecksetzen
    // und man saehe nie mehr als die ersten paar Zeichen.
    if (text !== lastMarqueeText) {
      els.subtitle.innerHTML = `<span class="marquee-text">${escapeHtml(text)}</span>`;
      els.subtitle.classList.add("marquee");
      lastMarqueeText = text;
      // Erst nach dem Einfuegen ins DOM messen, sonst ist scrollWidth 0.
      requestAnimationFrame(startMarqueeAnimation);
    }
  } else {
    if (currentMarqueeAnimation) {
      currentMarqueeAnimation.cancel();
      currentMarqueeAnimation = null;
    }
    els.subtitle.textContent = text;
    els.subtitle.classList.remove("marquee");
    lastMarqueeText = null;
  }
}

async function refreshStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();

    if (!data.active) {
      els.title.textContent = "Kein Titel aktiv";
      setSubtitle("\u00A0", false);
      els.cover.hidden = true;
      els.playPause.textContent = "▶";
    } else {
      els.title.textContent = data.name || data.title || "—";
      if (data.source === "webradio" && data.song_title) {
        // Aktueller Songtitel aus den ICY-Stream-Metadaten - als
        // Rechts-nach-links-Lauftext, da er oft laenger ist als die Zeile.
        setSubtitle(data.song_title, true);
      } else {
        setSubtitle(data.artist || data.country || "\u00A0", false);
      }
      if (data.album_cover) {
        els.cover.src = data.album_cover;
        els.cover.hidden = false;
      } else {
        els.cover.hidden = true;
      }
      els.playPause.textContent = data.is_playing ? "⏸" : "▶";
      if (typeof data.volume_percent === "number") {
        els.volume.value = data.volume_percent;
      }
    }

    els.next.disabled = !data.can_skip;
    els.prev.disabled = !data.can_skip;

    if (data.source === "spotify") {
      els.deviceToggle.textContent = data.device_name
        ? `🔊 ${data.device_name}`
        : "🔊 Ausgabegerät wählen";
      els.playbackModes.hidden = false;
      state.shuffleOn = !!data.shuffle_state;
      state.repeatMode = data.repeat_state || "off";
      els.btnShuffle.classList.toggle("active", state.shuffleOn);
      updateRepeatButtonVisual();
    } else {
      els.playbackModes.hidden = true;
    }

    if (data.source === "usb") {
      // Die rechte Spalte selbst wird von den USB-Funktionen verwaltet,
      // aber welcher Titel darin gruen markiert ist, muss bei jedem Poll
      // aktualisiert werden - sonst bleibt beim Weiterspringen (Buttons
      // oder automatischer Start) die alte Markierung stehen.
      updateUsbActiveTrack(data.path);
    }

    if (data.source === "spotify") {
      // Genau wie bei USB: laeuft unabhaengig davon, ob die rechte Spalte
      // gerade "Aktuelles Album" (auto) oder eine angepinnte Playlist
      // zeigt - sonst bleibt im Playlist-Modus nie ein Titel markiert,
      // da updateCurrentAlbumPanel() dort ja bewusst nichts tut.
      updateSpotifyActiveTrack(data.active ? data.uri : null);
    }

    updateCurrentAlbumPanel(data);
  } catch (e) {
    // Backend evtl. noch nicht bereit - beim naechsten Poll erneut versuchen
  }
}

function updateUsbActiveTrack(path) {
  if (!path) return;
  els.currentAlbumTracks.querySelectorAll(".result-item").forEach((li) => {
    li.classList.toggle("track-active", li.dataset.path === path);
  });
}

function updateSpotifyActiveTrack(uri) {
  els.currentAlbumTracks.querySelectorAll(".result-item").forEach((li) => {
    li.classList.toggle("track-active", !!uri && li.dataset.uri === uri);
  });
}

setInterval(refreshStatus, 2000);
refreshStatus();

els.playPause.addEventListener("click", async () => {
  const isPlaying = els.playPause.textContent === "⏸";
  await fetch(isPlaying ? "/api/pause" : "/api/play", { method: "POST" });
  refreshStatus();
});

els.next.addEventListener("click", () => fetch("/api/next", { method: "POST" }).then(refreshStatus));
els.prev.addEventListener("click", () => fetch("/api/previous", { method: "POST" }).then(refreshStatus));

els.volume.addEventListener("change", () => {
  fetch("/api/volume", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ level: Number(els.volume.value) }),
  });
});

// --- Aktuelles Album (rechte Seitenleiste) --------------------------------------

function highlightActiveTrack() {
  els.currentAlbumTracks.querySelectorAll(".result-item").forEach((li) => {
    li.classList.toggle("track-active", li.dataset.uri === state.currentTrackUri);
  });
}

async function updateCurrentAlbumPanel(data) {
  if (state.rightPanelMode !== "auto") {
    // Die rechte Spalte ist "angepinnt" (USB-Ordner-Ansicht oder eine manuell
    // ausgewaehlte Playlist) - hier nichts tun, damit der naechste
    // Status-Poll sie nicht wieder ueberschreibt.
    return;
  }
  if (data.source !== "spotify" || !data.active || !data.album_id) {
    state.currentAlbumId = null;
    state.currentTrackUri = null;
    els.currentAlbumCover.hidden = true;
    els.currentAlbumName.textContent = "Kein Album aktiv";
    els.currentAlbumArtist.textContent = "\u00A0";
    els.currentAlbumTracks.innerHTML = "";
    return;
  }

  state.currentTrackUri = data.uri || null;

  if (data.album_id === state.currentAlbumId) {
    // Gleiches Album wie beim letzten Poll - nur die Hervorhebung des
    // laufenden Titels aktualisieren, nicht die Titelliste neu laden.
    highlightActiveTrack();
    return;
  }

  state.currentAlbumId = data.album_id;
  els.currentAlbumName.textContent = data.album_name || data.name;
  els.currentAlbumArtist.textContent = data.artist || "\u00A0";
  if (data.album_cover) {
    els.currentAlbumCover.src = data.album_cover;
    els.currentAlbumCover.hidden = false;
  } else {
    els.currentAlbumCover.hidden = true;
  }

  els.currentAlbumTracks.innerHTML = '<li class="result-empty">Lade Titel…</li>';
  try {
    const res = await fetch(`/api/spotify/album/${data.album_id}/tracks`);
    const tracks = await res.json();
    if (tracks.error) {
      els.currentAlbumTracks.innerHTML = `<li class="result-empty">Fehler: ${tracks.error}</li>`;
      return;
    }
    els.currentAlbumTracks.innerHTML = "";
    tracks.forEach((track) => {
      const li = document.createElement("li");
      li.className = "result-item";
      li.dataset.uri = track.uri;
      li.innerHTML = `
        <div class="result-text">
          <div class="result-title">${track.track_number ? track.track_number + ". " : ""}${track.name}</div>
          <div class="result-subtitle">${track.artist}</div>
        </div>`;
      li.addEventListener("click", () => playUri(track.uri));
      els.currentAlbumTracks.appendChild(li);
    });
    highlightActiveTrack();
  } catch (err) {
    els.currentAlbumTracks.innerHTML = '<li class="result-empty">Titel konnten nicht geladen werden.</li>';
  }
}

// --- Spotify-Ausgabegerät ------------------------------------------------------

function deviceIcon(type) {
  const icons = { Computer: "💻", Smartphone: "📱", Speaker: "🔊", TV: "📺", AVR: "🎚️" };
  return icons[type] || "🔊";
}

els.deviceToggle.addEventListener("click", async () => {
  if (!els.deviceList.hidden) {
    els.deviceList.hidden = true;
    return;
  }
  const res = await fetch("/api/spotify/devices");
  const devices = await res.json();
  els.deviceList.innerHTML = "";
  if (devices.length === 0) {
    els.deviceList.innerHTML =
      '<li class="result-empty">Kein Gerät gefunden – ist irgendwo die Spotify-App geöffnet?</li>';
  }
  devices.forEach((d) => {
    const li = document.createElement("li");
    li.className = "result-item" + (d.is_active ? " device-active" : "");
    li.innerHTML = `
      <div class="result-text">
        <div class="result-title">${deviceIcon(d.type)} ${d.name}</div>
        <div class="result-subtitle">${d.is_active ? "aktiv" : d.type}</div>
      </div>`;
    li.addEventListener("click", async () => {
      await fetch("/api/spotify/device", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_id: d.id }),
      });
      els.deviceList.hidden = true;
      refreshStatus();
    });
    els.deviceList.appendChild(li);
  });
  els.deviceList.hidden = false;
});

// --- Eigene Playlists (im selben Stil wie Alben: Cover=Play, Pfeil=Details) ------

let albumsView = "online"; // "online" | "playlists" | "albums" - was GERADE angezeigt wird (kann automatisch wechseln)
// Wo eine NEU eingegebene Suche standardmaessig hinsucht - aendert sich
// bewusst NUR, wenn der Nutzer selbst auf einen Reiter klickt, nicht wenn
// switchToAlbumsView() nach Auswahl eines Hoerspiele-Ergebnisses automatisch
// zum Spotify-Reiter wechselt, um dessen Treffer zu zeigen (siehe
// Chat-Verlauf: sonst wuerde eine erneute Suche direkt bei Spotify statt
// wieder erst extern landen, obwohl der Nutzer den Reiter nie selbst
// gewechselt hat).
let searchMode = "online";

function updateAlbumsViewUI() {
  els.albumSubtabs.forEach((t) => t.classList.toggle("active", t.dataset.view === albumsView));
  els.albumResults.hidden = albumsView !== "albums";
  els.playlistsList.hidden = albumsView !== "playlists";
  els.onlineResults.hidden = albumsView !== "online";
  const columnHeading = document.getElementById("album-column-title");
  if (columnHeading) {
    columnHeading.textContent =
      albumsView === "online" ? "Hörspiele" : albumsView === "playlists" ? "Playlists" : "Spotify";
  }
  const panelHeading = document.getElementById("current-album-heading");
  if (panelHeading) panelHeading.textContent = albumsView === "playlists" ? "Aktuelle Playlist" : "Aktuelles Album";
  if (albumsView === "playlists" && !state.playlistsCache) {
    loadSpotifyPlaylists();
  }
  if (albumsView === "online" && !els.onlineResults.innerHTML.trim()) {
    els.onlineResults.innerHTML =
      '<li class="result-empty">Suchbegriff eingeben und suchen - durchsucht zuerst eine externe Datenbank, um Spotify-Anfragen zu sparen.</li>';
  }
}

els.albumSubtabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    albumsView = tab.dataset.view;
    searchMode = albumsView; // bewusste manuelle Wahl - gilt auch fuer die naechste Suche
    updateAlbumsViewUI();
  });
});

// Initialen Zustand einmal anwenden, da "online" (Hörspiele) jetzt der
// Standard-Reiter ist - ohne das würde die Titel-Spalte beim allerersten
// Laden der Seite noch keinen Hinweistext zeigen.
updateAlbumsViewUI();

async function loadSpotifyPlaylists() {
  els.playlistsList.innerHTML = '<li class="result-empty">Lade Playlists…</li>';
  try {
    const res = await fetch("/api/spotify/playlists");
    const data = await res.json();
    if (data.error || !Array.isArray(data)) {
      els.playlistsList.innerHTML = `<li class="result-empty">Playlists konnten nicht geladen werden${data.error ? ": " + data.error : ""}.</li>`;
      return;
    }
    state.playlistsCache = data;
    renderPlaylistsList(data);
  } catch (err) {
    els.playlistsList.innerHTML = '<li class="result-empty">Playlists konnten nicht geladen werden.</li>';
  }
}

function renderPlaylistsList(playlists) {
  els.playlistsList.innerHTML = "";
  if (playlists.length === 0) {
    els.playlistsList.innerHTML = '<li class="result-empty">Keine Playlists gefunden.</li>';
    return;
  }
  playlists.forEach((pl) => {
    const li = document.createElement("li");
    li.className = "result-item" + (pl.id === state.activePlaylistId ? " album-active" : "");
    li.dataset.id = pl.id;
    li.innerHTML = `
      <div class="album-cover-wrap" title="Playlist abspielen">
        ${pl.cover ? `<img src="${pl.cover}" alt="">` : '<span class="folder-icon">🎵</span>'}
        <span class="album-play-badge"></span>
      </div>
      <div class="result-text">
        <div class="result-title">${pl.name}</div>
        <div class="result-subtitle">${pl.track_count} Titel${pl.owned === false ? " · gespeichert (keine Titelanzeige möglich)" : ""}</div>
      </div>
      <button type="button" class="album-expand-toggle" title="Titel anzeigen">▾</button>`;

    li.querySelector(".album-cover-wrap").addEventListener("click", (e) => {
      e.stopPropagation();
      playPlaylist(pl);
    });
    li.querySelector(".album-expand-toggle").addEventListener("click", (e) => {
      e.stopPropagation();
      browsePlaylist(pl);
    });
    els.playlistsList.appendChild(li);
  });
}

function renderSpotifyRightPanelTracks(tracks) {
  els.currentAlbumTracks.innerHTML = "";
  if (tracks.length === 0) {
    els.currentAlbumTracks.innerHTML = '<li class="result-empty">Keine Titel in dieser Playlist.</li>';
    return;
  }
  tracks.forEach((track) => {
    const li = document.createElement("li");
    li.className = "result-item";
    li.dataset.uri = track.uri;
    li.innerHTML = `
      ${track.album_cover ? `<img src="${track.album_cover}" alt="">` : ""}
      <div class="result-text">
        <div class="result-title">${track.name}</div>
        <div class="result-subtitle">${track.artist}</div>
      </div>`;
    li.addEventListener("click", () => playUri(track.uri));
    li.appendChild(createAddButton(track.uri));
    els.currentAlbumTracks.appendChild(li);
  });
}

// Zeigt eine Playlist rechts an (genau wie das aktuelle Album), ohne
// zwangsläufig etwas abzuspielen - fürs reine Durchstöbern.
async function browsePlaylist(playlist) {
  state.rightPanelMode = "playlist";
  state.currentPlaylistId = playlist.id;
  els.currentAlbumName.textContent = playlist.name;
  els.currentAlbumArtist.textContent = `Playlist · ${playlist.track_count} Titel`;
  if (playlist.cover) {
    els.currentAlbumCover.src = playlist.cover;
    els.currentAlbumCover.hidden = false;
  } else {
    els.currentAlbumCover.hidden = true;
  }
  els.currentAlbumTracks.innerHTML = '<li class="result-empty">Lade Titel…</li>';
  try {
    const res = await fetch(`/api/spotify/playlist/${playlist.id}/tracks`);
    const tracks = await res.json();
    if (tracks.error) {
      els.currentAlbumTracks.innerHTML = `<li class="result-empty">Fehler: ${tracks.error}</li>`;
      return;
    }
    if (tracks.length === 0 && playlist.owned === false) {
      // Spotify liefert seit Februar 2026 keine Titelinhalte mehr fuer
      // Playlists, die nur gespeichert/gefolgt (nicht selbst erstellt)
      // wurden - das erklaeren, statt nur "keine Titel" zu zeigen.
      els.currentAlbumTracks.innerHTML =
        '<li class="result-empty">Spotify zeigt für gespeicherte/fremde Playlists (die du nicht selbst erstellt hast) seit Februar 2026 keine Titelliste mehr an. Funktioniert nur bei eigenen Playlists.</li>';
      return;
    }
    renderSpotifyRightPanelTracks(tracks);
  } catch (err) {
    els.currentAlbumTracks.innerHTML = '<li class="result-empty">Titel konnten nicht geladen werden.</li>';
  }
}

// Spielt die Playlist sofort ab UND zeigt sie rechts an (Pendant zum
// Cover-Klick bei Alben).
async function playPlaylist(playlist) {
  await fetch("/api/spotify/playlist/play", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ playlist_id: playlist.id }),
  });
  refreshStatus();
  markNowPlayingActive({ playlistId: playlist.id });
  browsePlaylist(playlist);
}

// --- Zufällige Wiedergabe / Wiederholen -------------------------------------------

function updateRepeatButtonVisual() {
  els.btnRepeat.classList.toggle("active", state.repeatMode !== "off");
  els.btnRepeat.textContent = state.repeatMode === "track" ? "🔂" : "🔁";
  els.btnRepeat.title =
    state.repeatMode === "track"
      ? "Titel wiederholen (aktiv) – klicken zum Ausschalten"
      : state.repeatMode === "context"
        ? "Playlist/Album wiederholen (aktiv) – klicken für Titel-Wiederholung"
        : "Wiederholen ausgeschaltet – klicken für Playlist/Album-Wiederholung";
}

els.btnShuffle.addEventListener("click", async () => {
  state.shuffleOn = !state.shuffleOn;
  els.btnShuffle.classList.toggle("active", state.shuffleOn);
  await fetch("/api/spotify/shuffle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled: state.shuffleOn }),
  });
});

els.btnRepeat.addEventListener("click", async () => {
  const order = ["off", "context", "track"];
  state.repeatMode = order[(order.indexOf(state.repeatMode) + 1) % order.length];
  updateRepeatButtonVisual();
  await fetch("/api/spotify/repeat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: state.repeatMode }),
  });
});

// --- Spotify-Suche -----------------------------------------------------------

async function playUri(uri) {
  await fetch("/api/spotify/play", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ uri }),
  });
  refreshStatus();
}

// --- "Zu Playlist hinzufügen" (wiederverwendbar: Suche, aktuelles Album, Playlist-Ansicht) ---

async function ensurePlaylistsLoaded() {
  if (state.playlistsCache) return state.playlistsCache;
  try {
    const res = await fetch("/api/spotify/playlists");
    const data = await res.json();
    state.playlistsCache = Array.isArray(data) ? data : [];
  } catch (err) {
    state.playlistsCache = [];
  }
  return state.playlistsCache;
}

async function showAddToPlaylistMenu(anchorLi, trackUri) {
  document.querySelectorAll(".add-to-playlist-menu").forEach((el) => el.remove());

  const menu = document.createElement("ul");
  menu.className = "add-to-playlist-menu result-list";
  menu.innerHTML = '<li class="result-empty">Lade Playlists…</li>';
  anchorLi.appendChild(menu);

  const playlists = await ensurePlaylistsLoaded();
  menu.innerHTML = "";
  if (playlists.length === 0) {
    menu.innerHTML = '<li class="result-empty">Keine Playlists gefunden.</li>';
    return;
  }
  playlists.forEach((pl) => {
    const li = document.createElement("li");
    li.className = "result-item";
    li.innerHTML = `<div class="result-text"><div class="result-title">${pl.name}</div></div>`;
    li.addEventListener("click", async (e) => {
      e.stopPropagation();
      li.querySelector(".result-title").textContent = "Wird hinzugefügt…";
      await fetch("/api/spotify/playlist/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ playlist_id: pl.id, uri: trackUri }),
      });
      li.querySelector(".result-title").textContent = `✓ ${pl.name}`;
      setTimeout(() => menu.remove(), 700);
    });
    menu.appendChild(li);
  });
}

function createAddButton(trackUri) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "add-to-playlist-btn";
  btn.title = "Zu Playlist hinzufügen";
  btn.textContent = "➕";
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    const anchorLi = btn.closest(".result-item");
    const existingMenu = anchorLi.querySelector(".add-to-playlist-menu");
    if (existingMenu) {
      existingMenu.remove();
      return;
    }
    showAddToPlaylistMenu(anchorLi, trackUri);
  });
  return btn;
}

function renderTrackResults(items, append) {
  if (!append) els.trackResults.innerHTML = "";
  if (!append && items.length === 0) {
    els.trackResults.innerHTML = '<li class="result-empty">Keine Treffer.</li>';
  }
  items.forEach((item) => {
    const li = document.createElement("li");
    li.className = "result-item";
    li.innerHTML = `
      ${item.album_cover ? `<img src="${item.album_cover}" alt="">` : ""}
      <div class="result-text">
        <div class="result-title">${item.name}</div>
        <div class="result-subtitle">${item.artist}</div>
      </div>`;
    li.addEventListener("click", () => playUri(item.uri));
    li.appendChild(createAddButton(item.uri));
    els.trackResults.appendChild(li);
  });
}

function switchToAlbumsView() {
  // Wird aufgerufen, wenn ein Album aus der Suche abgespielt wird - stellt
  // sicher, dass Umschalter und rechte Spalte konsistent auf "Spotify"
  // (die Alben-Ergebnisliste) zurückspringen, auch wenn gerade
  // "Playlists"/"Hörspiele" aktiv war bzw. eine Playlist rechts
  // "angepinnt" war.
  albumsView = "albums";
  updateAlbumsViewUI();
  state.rightPanelMode = "auto";
}

function markNowPlayingActive({ albumUri = null, playlistId = null } = {}) {
  // Nur EINE Markierung gleichzeitig aktiv, da ja auch nur eins wirklich
  // spielen kann - setzt man das eine, wird das andere automatisch geloescht.
  state.activeAlbumUri = albumUri;
  state.activePlaylistId = playlistId;
  els.albumResults.querySelectorAll(".result-item").forEach((li) => {
    li.classList.toggle("album-active", li.dataset.uri === albumUri);
  });
  els.playlistsList.querySelectorAll(".result-item").forEach((li) => {
    li.classList.toggle("album-active", li.dataset.id === playlistId);
  });
}

function renderAlbumResults(items, append) {
  if (!append) els.albumResults.innerHTML = "";
  if (!append && items.length === 0) {
    els.albumResults.innerHTML = '<li class="result-empty">Keine Treffer.</li>';
  }
  items.forEach((album) => {
    const li = document.createElement("li");
    li.className = "result-item" + (album.uri === state.activeAlbumUri ? " album-active" : "");
    li.dataset.uri = album.uri;
    li.innerHTML = `
      <div class="album-cover-wrap" title="Album abspielen">
        ${album.album_cover ? `<img src="${album.album_cover}" alt="">` : ""}
        <span class="album-play-badge"></span>
      </div>
      <div class="result-text">
        <div class="result-title">${album.name}</div>
        <div class="result-subtitle">${album.artist}</div>
      </div>
      <button type="button" class="album-expand-toggle" title="Titel anzeigen">▾</button>`;

    li.querySelector(".album-cover-wrap").addEventListener("click", (e) => {
      e.stopPropagation();
      switchToAlbumsView();
      markNowPlayingActive({ albumUri: album.uri });
      playUri(album.uri);
    });
    li.querySelector(".album-expand-toggle").addEventListener("click", (e) => {
      e.stopPropagation();
      toggleAlbumTracks(li, album, e.currentTarget);
    });

    els.albumResults.appendChild(li);
  });
}

async function toggleAlbumTracks(li, album, toggleBtn) {
  // Bereits aufgeklappt? Dann einklappen (naechstes Element entfernen).
  const existing = li.nextElementSibling;
  if (existing && existing.classList.contains("album-tracks-wrapper")) {
    existing.remove();
    toggleBtn.classList.remove("expanded");
    toggleBtn.textContent = "▾";
    return;
  }
  // Andere offene Album-Aufklappungen schliessen, damit die Liste uebersichtlich bleibt.
  els.albumResults.querySelectorAll(".album-tracks-wrapper").forEach((el) => el.remove());
  els.albumResults.querySelectorAll(".album-expand-toggle.expanded").forEach((btn) => {
    btn.classList.remove("expanded");
    btn.textContent = "▾";
  });

  toggleBtn.classList.add("expanded");
  toggleBtn.textContent = "▴";

  const albumId = album.uri.split(":").pop();
  const wrapper = document.createElement("div");
  wrapper.className = "album-tracks-wrapper";
  wrapper.innerHTML = '<div class="result-empty">Lade Titel…</div>';
  li.after(wrapper);

  try {
    const res = await fetch(`/api/spotify/album/${albumId}/tracks`);
    const tracks = await res.json();
    if (tracks.error) {
      wrapper.innerHTML = `<div class="result-empty">Fehler: ${tracks.error}</div>`;
      return;
    }
    const ul = document.createElement("ul");
    ul.className = "album-tracks";
    tracks.forEach((track) => {
      const trackLi = document.createElement("li");
      trackLi.className = "result-item";
      trackLi.innerHTML = `
        <div class="result-text">
          <div class="result-title">${track.track_number ? track.track_number + ". " : ""}${track.name}</div>
          <div class="result-subtitle">${track.artist}</div>
        </div>`;
      trackLi.addEventListener("click", () => playUri(track.uri));
      ul.appendChild(trackLi);
    });
    wrapper.innerHTML = "";
    wrapper.appendChild(ul);
  } catch (err) {
    wrapper.innerHTML = '<div class="result-empty">Titel konnten nicht geladen werden.</div>';
  }
}

async function runSpotifySearch(query) {
  state.spotifyQuery = query;
  state.spotifyOffsets = { track: 0, album: 0 };
  state.spotifyExhausted = { track: false, album: false };
  els.trackResults.innerHTML = '<li class="result-empty">Suche läuft…</li>';
  els.albumResults.innerHTML = '<li class="result-empty">Suche läuft…</li>';
  try {
    const res = await fetch(`/api/spotify/search_combined?q=${encodeURIComponent(query)}`);
    const data = await res.json();
    if (data.error) {
      const msg = `<li class="result-empty">Fehler bei der Suche: ${data.error}</li>`;
      els.trackResults.innerHTML = msg;
      els.albumResults.innerHTML = msg;
      return;
    }
    if (data.blocked) {
      const msg = '<li class="result-error">🚫 Dieser Suchbegriff ist gesperrt.</li>';
      els.trackResults.innerHTML = msg;
      els.albumResults.innerHTML = msg;
      state.spotifyExhausted.track = true;
      state.spotifyExhausted.album = true;
      return;
    }
    renderTrackResults(data.tracks, false);
    renderAlbumResults(data.albums, false);
    state.spotifyExhausted.track = data.tracks.length < 10;
    state.spotifyExhausted.album = data.albums.length < 10;
  } catch (err) {
    const msg =
      '<li class="result-empty">Suche fehlgeschlagen – läuft die App noch und bist du mit Spotify verbunden?</li>';
    els.trackResults.innerHTML = msg;
    els.albumResults.innerHTML = msg;
  }
}

async function runExternalSearch(query) {
  els.onlineResults.innerHTML = '<li class="result-empty">Suche in externer Datenbank…</li>';
  try {
    const res = await fetch(`/api/external/search?q=${encodeURIComponent(query)}`);
    const results = await res.json();
    renderExternalResults(results);
  } catch (err) {
    els.onlineResults.innerHTML = '<li class="result-empty">Suche fehlgeschlagen (keine Verbindung?).</li>';
  }
}

function renderExternalResults(items) {
  els.onlineResults.innerHTML = "";
  if (items.length === 0) {
    els.onlineResults.innerHTML = '<li class="result-empty">Keine Treffer in der externen Datenbank.</li>';
    return;
  }
  items.forEach((item) => {
    const li = document.createElement("li");
    li.className = "result-item";
    li.innerHTML = `
      <div class="album-cover-wrap" title="Bei Spotify suchen">
        ${item.cover ? `<img src="${item.cover}" alt="">` : '<span class="folder-icon">💿</span>'}
      </div>
      <div class="result-text">
        <div class="result-title">${item.title}</div>
        <div class="result-subtitle">${item.artist}${item.release_year ? " · " + item.release_year : ""}</div>
      </div>`;
    li.addEventListener("click", () => selectExternalResult(item));
    els.onlineResults.appendChild(li);
  });
}

async function selectExternalResult(item) {
  // Zeigt kurz eine Ladeanzeige direkt an der angeklickten Stelle, damit
  // klar ist, dass jetzt die gezielte (einzelne!) Spotify-Suche laeuft -
  // nicht der teure Katalog-Crawl, den wir mit diesem Modus ja gerade
  // vermeiden wollen.
  els.onlineResults.innerHTML = '<li class="result-empty">Suche gezielt bei Spotify…</li>';
  try {
    const params = new URLSearchParams({ artist: item.artist, title: item.title });
    const res = await fetch(`/api/spotify/search_for_album?${params}`);
    const albums = await res.json();
    if (albums.error) {
      els.onlineResults.innerHTML = `<li class="result-empty">Fehler: ${albums.error}</li>`;
      return;
    }
    switchToAlbumsView();
    renderAlbumResults(albums, false);
    if (albums.length === 0) {
      els.albumResults.innerHTML =
        '<li class="result-empty">Bei Spotify nicht gefunden. Über den "Hörspiele"-Reiter zurück zur Vorab-Suche und ggf. ein anderes Ergebnis probieren.</li>';
    }
  } catch (err) {
    els.onlineResults.innerHTML = '<li class="result-empty">Suche fehlgeschlagen (keine Verbindung?).</li>';
  }
}

els.spotifyForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const query = els.spotifyInput.value.trim();
  if (!query) return;
  if (searchMode === "online") {
    // Titel-Suche bewusst uebersprungen: die nutzt intern dieselbe
    // Best-Of-Album-Heuristik, die bei umfangreichen Diskografien ebenfalls
    // einen teuren Katalog-Crawl ausloesen kann - genau das, was der
    // Hörspiele-Modus ja vermeiden soll.
    els.trackResults.innerHTML =
      '<li class="result-empty">Im Hörspiele-Modus deaktiviert (würde denselben teuren Diskografie-Katalog laden). Erst links ein Ergebnis auswählen.</li>';
    // Anzeige zurueck auf "Hörspiele" schalten, falls sie zwischenzeitlich
    // (durch Auswahl eines vorherigen Ergebnisses) automatisch auf
    // "Spotify" gesprungen war - die neue Suche soll sichtbar wieder dort
    // stattfinden, wo sie laut searchMode auch tatsaechlich hingeht.
    albumsView = "online";
    updateAlbumsViewUI();
    runExternalSearch(query);
  } else {
    runSpotifySearch(query);
  }
});

// Infinite Scroll: sobald man in einer der beiden Spalten fast am unteren
// Rand ankommt, automatisch die naechsten 10 Treffer nachladen - kein Button
// noetig.
async function loadMoreResults(type) {
  if (state.spotifyLoading[type] || state.spotifyExhausted[type] || !state.spotifyQuery) return;
  state.spotifyLoading[type] = true;
  state.spotifyOffsets[type] += 10;
  try {
    const res = await fetch(
      `/api/spotify/search?q=${encodeURIComponent(state.spotifyQuery)}&type=${type}&offset=${state.spotifyOffsets[type]}`
    );
    const data = await res.json();
    if (!data.error) {
      if (type === "track") renderTrackResults(data, true);
      else renderAlbumResults(data, true);
      state.spotifyExhausted[type] = data.length < 10;
    }
  } finally {
    state.spotifyLoading[type] = false;
  }
}

function attachInfiniteScroll(listEl, type) {
  listEl.addEventListener("scroll", () => {
    const nearBottom = listEl.scrollTop + listEl.clientHeight >= listEl.scrollHeight - 32;
    if (nearBottom) loadMoreResults(type);
  });
}

attachInfiniteScroll(els.trackResults, "track");
attachInfiniteScroll(els.albumResults, "album");

// --- Web-Radio-Suche -----------------------------------------------------------

async function playRadioStation(url, name) {
  await fetch("/api/radio/play", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, name }),
  });
  refreshStatus();
}

async function toggleRadioVariants(li, station) {
  const toggleBtn = li.querySelector(".album-expand-toggle");
  const existing = li.nextElementSibling;
  if (existing && existing.classList.contains("album-tracks-wrapper")) {
    existing.remove();
    toggleBtn.classList.remove("expanded");
    toggleBtn.textContent = "▾";
    return;
  }
  els.radioResults.querySelectorAll(".album-tracks-wrapper").forEach((el) => el.remove());
  els.radioResults.querySelectorAll(".album-expand-toggle.expanded").forEach((btn) => {
    btn.classList.remove("expanded");
    btn.textContent = "▾";
  });
  toggleBtn.classList.add("expanded");
  toggleBtn.textContent = "▴";

  const wrapper = document.createElement("div");
  wrapper.className = "album-tracks-wrapper";
  const ul = document.createElement("ul");
  ul.className = "album-tracks";
  station.variants.forEach((variant) => {
    const varLi = document.createElement("li");
    varLi.className = "result-item";
    varLi.innerHTML = `
      <div class="result-text">
        <div class="result-title">${station.name}</div>
        <div class="result-subtitle">${variant.label}</div>
      </div>`;
    varLi.addEventListener("click", () => playRadioStation(variant.url, station.name));
    ul.appendChild(varLi);
  });
  wrapper.appendChild(ul);
  li.after(wrapper);
}

els.radioForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = els.radioInput.value.trim();
  if (!query) return;
  els.radioResults.innerHTML = '<li class="result-empty">Suche läuft…</li>';
  const res = await fetch(`/api/radio/search?q=${encodeURIComponent(query)}`);
  const stations = await res.json();
  els.radioResults.innerHTML = "";
  if (stations.length === 0) {
    els.radioResults.innerHTML = '<li class="result-empty">Keine Sender gefunden.</li>';
    return;
  }
  stations.forEach((station) => {
    const li = document.createElement("li");
    li.className = "result-item";
    const hasVariants = station.variants && station.variants.length > 1;
    li.innerHTML = `
      <div class="album-cover-wrap" title="Sender abspielen">
        ${station.favicon ? `<img src="${station.favicon}" alt="">` : '<span class="folder-icon">📻</span>'}
        <span class="album-play-badge"></span>
      </div>
      <div class="result-text">
        <div class="result-title">${station.name}</div>
        <div class="result-subtitle">${station.country || ""}</div>
      </div>
      ${hasVariants ? '<button type="button" class="album-expand-toggle" title="Qualität wählen">▾</button>' : ""}`;

    li.querySelector(".album-cover-wrap").addEventListener("click", (e) => {
      e.stopPropagation();
      playRadioStation(station.url, station.name);
    });
    if (hasVariants) {
      li.querySelector(".album-expand-toggle").addEventListener("click", (e) => {
        e.stopPropagation();
        toggleRadioVariants(li, station);
      });
    }
    els.radioResults.appendChild(li);
  });
});

// --- USB-Erkennung ---------------------------------------------------------------

function renderUsbRightPanelTracks(title, subtitle, tracks, activePath) {
  els.currentAlbumName.textContent = title;
  els.currentAlbumArtist.textContent = subtitle || "\u00A0";
  els.currentAlbumCover.hidden = true;
  els.currentAlbumTracks.innerHTML = "";
  if (tracks.length === 0) {
    els.currentAlbumTracks.innerHTML = '<li class="result-empty">Keine Titel gefunden.</li>';
    return;
  }
  tracks.forEach((track) => {
    const li = document.createElement("li");
    li.className = "result-item" + (track.path === activePath ? " track-active" : "");
    li.dataset.path = track.path;
    li.innerHTML = `
      <div class="result-text">
        <div class="result-title">${track.title}</div>
        <div class="result-subtitle">${track.artist || ""}</div>
      </div>`;
    li.addEventListener("click", async () => {
      await fetch("/api/usb/play", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: track.path }),
      });
      refreshStatus();
      els.currentAlbumTracks.querySelectorAll(".result-item").forEach((el) => {
        el.classList.toggle("track-active", el.dataset.path === track.path);
      });
    });
    els.currentAlbumTracks.appendChild(li);
  });
}

async function playUsbFolder(path, name) {
  await fetch("/api/usb/folder/play", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  refreshStatus();
  const res = await fetch(`/api/usb/folder_tracks?path=${encodeURIComponent(path)}`);
  const tracks = await res.json();
  renderUsbRightPanelTracks(name, "", tracks, tracks[0] && tracks[0].path);
}

function renderUsbFolderList(folders, parentPath) {
  els.usbResults.innerHTML = "";

  if (parentPath !== null) {
    const backLi = document.createElement("li");
    backLi.className = "result-item";
    backLi.innerHTML = '<div class="result-text"><div class="result-title">⬅ Zurück</div></div>';
    backLi.addEventListener("click", () => renderUsbBrowse(parentPath));
    els.usbResults.appendChild(backLi);
  }

  if (folders.length === 0) {
    if (parentPath === null) {
      els.usbResults.innerHTML = '<li class="result-empty">Keine Ordner mit MP3-Dateien gefunden.</li>';
    }
    return;
  }

  folders.forEach((folder) => {
    const li = document.createElement("li");
    li.className = "result-item";
    li.innerHTML = `
      <div class="album-cover-wrap" title="Ordner abspielen">
        <span class="folder-icon">📁</span>
        <span class="album-play-badge"></span>
      </div>
      <div class="result-text">
        <div class="result-title">${folder.name}</div>
      </div>
      <button type="button" class="album-expand-toggle" title="Öffnen">▸</button>`;

    li.querySelector(".album-cover-wrap").addEventListener("click", (e) => {
      e.stopPropagation();
      playUsbFolder(folder.path, folder.name);
    });
    const openFolder = () => renderUsbBrowse(folder.path);
    li.querySelector(".album-expand-toggle").addEventListener("click", (e) => {
      e.stopPropagation();
      openFolder();
    });
    li.querySelector(".result-text").addEventListener("click", openFolder);
    els.usbResults.appendChild(li);
  });
}

async function renderUsbBrowse(path) {
  const url = path ? `/api/usb/browse?path=${encodeURIComponent(path)}` : "/api/usb/browse";
  const res = await fetch(url);
  const info = await res.json();

  if (info.mode === "none") {
    els.usbResults.innerHTML = '<li class="result-empty">Kein USB-Stick ausgewählt.</li>';
    resetUsbRightPanel();
    return;
  }

  renderUsbFolderList(info.folders, info.is_root ? null : info.parent_path);

  els.currentAlbumCover.hidden = true;
  if (info.files.length > 0) {
    renderUsbRightPanelTracks(info.current_name, `USB-Stick: ${info.device_name}`, info.files);
  } else {
    els.currentAlbumName.textContent = info.current_name;
    els.currentAlbumArtist.textContent = `USB-Stick: ${info.device_name}`;
    els.currentAlbumTracks.innerHTML =
      info.folders.length > 0
        ? ""
        : '<li class="result-empty">Keine Titel in diesem Ordner.</li>';
  }
}

function resetUsbRightPanel() {
  els.currentAlbumName.textContent = "Kein USB-Stick aktiv";
  els.currentAlbumArtist.textContent = "\u00A0";
  els.currentAlbumCover.hidden = true;
  els.currentAlbumTracks.innerHTML = "";
}

async function selectUsbDevice(path) {
  await fetch("/api/usb/device", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  els.usbDevices.hidden = true;
  state.usbActiveDevicePath = path;
  els.usbEject.hidden = false;
  await renderUsbBrowse();
}

async function ejectUsbDevice() {
  if (!state.usbActiveDevicePath) return;
  els.usbEject.disabled = true;
  els.usbEject.textContent = "Wird ausgeworfen…";
  try {
    const res = await fetch("/api/usb/eject", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.usbActiveDevicePath }),
    });
    const result = await res.json();
    if (result.ok) {
      state.usbActiveDevicePath = null;
      els.usbEject.hidden = true;
      els.usbResults.innerHTML =
        '<li class="result-empty">✓ Stick sicher ausgeworfen - kann jetzt entfernt werden.</li>';
      resetUsbRightPanel();
    } else {
      els.usbResults.innerHTML = `<li class="result-empty">Auswerfen fehlgeschlagen: ${result.message || result.error || "unbekannter Fehler"}</li>`;
    }
  } catch (err) {
    els.usbResults.innerHTML = '<li class="result-empty">Auswerfen fehlgeschlagen (keine Verbindung zum Server).</li>';
  } finally {
    els.usbEject.disabled = false;
    els.usbEject.textContent = "⏏ Stick auswerfen";
  }
}

els.usbEject.addEventListener("click", ejectUsbDevice);

async function loadUsbList() {
  els.usbDevices.hidden = true;
  els.usbDevices.innerHTML = "";
  els.usbEject.hidden = true;
  state.usbActiveDevicePath = null;
  els.usbResults.innerHTML = '<li class="result-empty">Suche nach USB-Sticks…</li>';

  const res = await fetch("/api/usb/devices");
  const devices = await res.json();

  if (devices.length === 0) {
    els.usbResults.innerHTML =
      '<li class="result-empty">Kein USB-Stick mit MP3-Dateien gefunden. Im Dev-Modus: Dateien in den Ordner "sample_usb/" legen.</li>';
    resetUsbRightPanel();
    return;
  }

  if (devices.length === 1) {
    await selectUsbDevice(devices[0].path);
    return;
  }

  els.usbResults.innerHTML =
    '<li class="result-empty">Mehrere USB-Sticks gefunden – bitte auswählen:</li>';
  devices.forEach((d) => {
    const li = document.createElement("li");
    li.className = "result-item";
    li.innerHTML = `<div class="result-text"><div class="result-title">🔌 ${d.name}</div></div>`;
    li.addEventListener("click", () => selectUsbDevice(d.path));
    els.usbDevices.appendChild(li);
  });
  els.usbDevices.hidden = false;
}

els.usbRefresh.addEventListener("click", loadUsbList);
