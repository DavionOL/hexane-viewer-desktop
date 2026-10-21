#!/bin/sh
# Installiert Hexane Desk im Benutzerprofil (ohne Administratorrechte) und legt einen Eintrag im Anwendungsmenü an.
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${HEXANE_DESK_DEST:-$HOME/.local/opt/hexane-desk}"
mkdir -p "$DEST"
cp -a "$HERE"/. "$DEST"/
mkdir -p "$HOME/.local/bin"
ln -sf "$DEST/hexane-desk" "$HOME/.local/bin/hexane-desk"
"$DEST/hexane-desk" install-launcher
echo "Fertig. Zum Entfernen: rm -r \"$DEST\" ~/.local/bin/hexane-desk ~/.local/share/applications/hexane-desk.desktop"
