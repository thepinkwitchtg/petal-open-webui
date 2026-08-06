#!/bin/bash
# petal-build — rebuild OWUI frontend and re-seat the editable install 🌸
#   ./petal-build.sh          full build (svelte + editable re-seat)
#   ./petal-build.sh --skin   css + face fast lane, no npm, ~instant
set -e
cd ~/Gardens/petal-open-webui

SRC="static/static"
BUILD="build/static"
BACK="backend/open_webui/static"

# 🌸 the face — anything in this list gets carried by --skin.
FACE=(favicon.png favicon.ico favicon.svg favicon-96x96.png \
      logo.png splash.png splash-dark.png)

if [[ "$1" == "--skin" ]]; then
	# 🌸 skin-only sync.
	# writes to BOTH build/ and backend static, because config.py wipes
	# every top-level file in backend static on boot and repopulates it
	# from build/ — so build/ has to be truth or a restart eats the tweak.
	if [[ ! -d "$BUILD" ]]; then
		echo "💔 no build/ yet — run a full ./petal-build.sh first"
		exit 1
	fi

	for dest in "$BUILD" "$BACK"; do
		mkdir -p "$dest/petal"
		cp -r "$SRC/petal/." "$dest/petal/"
		cp "$SRC/custom.css" "$dest/custom.css"
		cp "$SRC/loader.js" "$dest/loader.js"

		for f in "${FACE[@]}"; do
			[[ -f "$SRC/$f" ]] && cp "$SRC/$f" "$dest/$f"
		done
	done

	# 🌸 sveltekit's own root-level favicon — separate lineage, same face
	[[ -f "$SRC/favicon.png" ]] && cp "$SRC/favicon.png" static/favicon.png
	[[ -f "$SRC/favicon.png" ]] && cp "$SRC/favicon.png" build/favicon.png

	echo "🌸 skin + face synced — hard-refresh Brave (ctrl+shift+r) 💅"
	exit 0
fi

echo "🌸 building frontend..."
NODE_OPTIONS="--max-old-space-size=8192" npm run build

echo "🌸 re-seating editable install..."
source ~/.venvs/openwebui/bin/activate
python -m pip install -e . --quiet

echo "✨ done~ restart open-webui serve to pick up changes"

# 🌸 self-heal the chroma tombstone ghost — safe in EITHER state:
#   owui up   → reports drift, defers, touches nothing
#   owui down → backs up + nukes in the safe window, your restart brings her back clean
chmod +x ./petal-ghost-check.sh