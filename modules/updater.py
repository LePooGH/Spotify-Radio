"""
Selbst-Update ueber Git/GitHub: prueft, ob im konfigurierten Remote-
Repository eine neuere Version verfuegbar ist, und kann sie per Knopfdruck
im Interface anwenden.

Setzt voraus, dass der Projektordner bereits ein Git-Repository mit einem
"origin"-Remote ist, der auf ein GitHub-Repository zeigt (z.B. `git clone
<repo-url>` beim Einrichten, oder nachtraeglich `git remote add origin
<repo-url>`).

WICHTIG: apply_update() setzt den lokalen Stand HART auf den Stand des
Remote-Branches (`git reset --hard`) - dabei gehen etwaige lokale, noch
nicht committete Aenderungen an versionierten Dateien verloren. Das ist so
gewollt: Das Geraet soll nach einem Update immer exakt dem GitHub-Stand
entsprechen, nicht ein Gemisch aus altem und neuem Code. Nicht versionierte
Dateien wie ".env" sind davon nicht betroffen (siehe .gitignore).
"""
import os
import subprocess
import sys


class Updater:
    def __init__(self, repo_path=".", branch="main"):
        self.repo_path = repo_path
        self.branch = branch

    def _run_git(self, *args, timeout=15):
        return subprocess.run(
            ["git", "-C", self.repo_path, *args],
            capture_output=True, text=True, timeout=timeout,
        )

    def check_for_update(self):
        """Prueft, ob im Remote-Repository eine neuere Version verfuegbar
        ist, OHNE sie schon anzuwenden. Braucht dafuer eine
        Internetverbindung (git fetch) - bei Netzwerkproblemen wird das als
        "kein Update verfuegbar" behandelt (mit Fehlermeldung), nicht als
        Absturz."""
        try:
            fetch = self._run_git("fetch", "origin", self.branch)
            if fetch.returncode != 0:
                return {"update_available": False, "error": fetch.stderr.strip()}

            local = self._run_git("rev-parse", "HEAD")
            remote = self._run_git("rev-parse", f"origin/{self.branch}")
            if local.returncode != 0 or remote.returncode != 0:
                return {"update_available": False, "error": "Konnte Versionsstand nicht ermitteln."}

            local_sha = local.stdout.strip()
            remote_sha = remote.stdout.strip()
            return {"update_available": local_sha != remote_sha, "error": None}
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return {"update_available": False, "error": str(exc)}

    def apply_update(self):
        """Wendet das Update an (git fetch + reset --hard auf den
        Remote-Branch), installiert danach ggf. neue/geaenderte Python-
        Abhaengigkeiten. Startet die App selbst NICHT neu - das entscheidet
        der Aufrufer (siehe app.py), je nachdem ob per systemd (Pi,
        automatischer Neustart) oder manuell (Dev-Modus) betrieben wird."""
        try:
            fetch = self._run_git("fetch", "origin", self.branch)
            if fetch.returncode != 0:
                return {"ok": False, "error": fetch.stderr.strip()}

            reset = self._run_git("reset", "--hard", f"origin/{self.branch}")
            if reset.returncode != 0:
                return {"ok": False, "error": reset.stderr.strip()}

            # Abhaengigkeiten aktualisieren, falls sich requirements.txt
            # geaendert hat - nicht fatal, falls das fehlschlaegt (z.B.
            # keine Verbindung zu PyPI), da der Code-Stand selbst schon
            # erfolgreich aktualisiert wurde.
            requirements_path = os.path.join(self.repo_path, "requirements.txt")
            pip_warning = None
            if os.path.exists(requirements_path):
                # sys.executable statt bloss "pip": stellt sicher, dass
                # immer die Python-Umgebung genutzt wird, mit der die App
                # selbst gerade laeuft (z.B. die venv), unabhaengig davon,
                # ob deren bin/-Ordner gerade im PATH steht - was z.B. beim
                # Start ueber systemd mit direktem venv/bin/python-Pfad
                # (siehe deploy/spotify-radio.service) nicht automatisch
                # der Fall ist.
                pip_result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-r", requirements_path, "--quiet"],
                    capture_output=True, text=True, timeout=120,
                )
                if pip_result.returncode != 0:
                    pip_warning = pip_result.stderr.strip()

            new_sha = self._run_git("rev-parse", "HEAD").stdout.strip()
            return {"ok": True, "new_version": new_sha[:7], "pip_warning": pip_warning}
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return {"ok": False, "error": str(exc)}
