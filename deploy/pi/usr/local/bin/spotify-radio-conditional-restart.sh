#!/bin/bash
# Naechtlicher Neustart der Radio-App (frische Spotify-Sitzung) -
# aber nur, wenn gerade nichts abgespielt wird.
STATUS=$(curl -s --max-time 10 http://localhost:5000/api/status)
PLAYING=$(echo "$STATUS" | python3 -c 'import sys, json
try:
    print(bool(json.load(sys.stdin).get("is_playing")))
except Exception:
    print(False)')
if [ "$PLAYING" = "True" ]; then
    echo "Wiedergabe laeuft - kein Neustart"
else
    systemctl restart spotify-radio.service
    echo "spotify-radio.service neu gestartet"
fi
