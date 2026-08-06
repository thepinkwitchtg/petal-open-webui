#!/bin/bash
# petal-ghost-check — the exorcist 🌸👁
#   detects OWUI's two-layer memory drift (SQLite memory table vs Chroma vector ghost),
#   then heals by nuking the *derived* vector store so it lazy-rebuilds from truth.
#
#   disk-is-truth · always backs up before it deletes · always leaves a record
#
#   usage:
#     ./petal-ghost-check.sh            # detect → auto-heal ONLY on confirmed drift (default)
#     ./petal-ghost-check.sh --check    # detect + report only, never touch disk (safe anywhere)
#     ./petal-ghost-check.sh --force    # backup + nuke regardless of drift (the "just do it" sledgehammer)
#
#   safety: refuses to nuke while owui is running (open handles = corruption).
#           if owui is up and a heal is warranted, it reports + defers with instructions.
set -euo pipefail

DATA="/gardens/petal-open-webui/backend/open_webui/data"
WEBUI_DB="$DATA/webui.db"
VECTOR_DB="$DATA/vector_db"
CHROMA="$VECTOR_DB/chroma.sqlite3"
LOG="$HOME/Gardens/petal-ghost-check.log"

MODE="${1:-auto}"

log() { printf '%s | %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" | tee -a "$LOG"; }

# ── owui running? (Launcher owns lifecycle — we never kill it, only refuse to nuke live)
owui_running() { pgrep -f 'open-webui serve' >/dev/null 2>&1; }

# ── layer 1: truth count (this is rock-solid)
mem_rows=0
if [[ -f "$WEBUI_DB" ]]; then
	mem_rows=$(sqlite3 "$WEBUI_DB" "SELECT COUNT(*) FROM memory;" 2>/dev/null || echo 0)
fi

# ── knowledge-base cost check: nuking vector_db re-embeds these on next access
kb=0; kbf=0
if [[ -f "$WEBUI_DB" ]]; then
	kb=$(sqlite3 "$WEBUI_DB"  "SELECT COUNT(*) FROM knowledge;"      2>/dev/null || echo 0)
	kbf=$(sqlite3 "$WEBUI_DB" "SELECT COUNT(*) FROM knowledge_file;" 2>/dev/null || echo 0)
fi

# ── layer 2: ghost count.  the ONE spot that depends on chroma's internal schema,
#    the ghost's true seat is the un-compacted write-ahead queue (embeddings_queue),
#    NOT the segment store — the segment store trails truth (lazy embed) and would lie.
#    chroma queue ops:  2 = add/upsert   3 = delete(tombstone)
#    the memory collection is scoped by topic: persistent://default/default/<collection-id>
#
#    we resolve the memory collection id dynamically (per-user, name prefixed
#    'user-memory-'), then count tombstoned deletes still sitting in the queue.
#    nonzero uncompacted deletes = residue semantic retrieval can still surface = ghost.
q_adds="?"; q_dels="?"; live_embeddings="?"
chroma_ok=false
if [[ -f "$CHROMA" ]]; then
	MEM_CID=$(sqlite3 "$CHROMA" \
		"SELECT id FROM collections WHERE name LIKE 'user-memory-%' LIMIT 1;" 2>/dev/null || echo "")
	if [[ -n "$MEM_CID" ]]; then
		TOPIC="persistent://default/default/$MEM_CID"
		q_adds=$(sqlite3 "$CHROMA" "SELECT COUNT(*) FROM embeddings_queue WHERE topic='$TOPIC' AND operation=2;" 2>/dev/null || echo "?")
		q_dels=$(sqlite3 "$CHROMA" "SELECT COUNT(*) FROM embeddings_queue WHERE topic='$TOPIC' AND operation=3;" 2>/dev/null || echo "?")
		live_embeddings=$(sqlite3 "$CHROMA" "SELECT COUNT(*) FROM embeddings e JOIN segments s ON e.segment_id=s.id WHERE s.collection='$MEM_CID';" 2>/dev/null || echo "?")
		[[ "$q_dels" != "?" ]] && chroma_ok=true
	fi
fi

log "── petal-ghost-check (mode=$MODE) ──"
log "layer 1  memory rows (truth)     : $mem_rows"
log "layer 2  live embeddings (seg)   : $live_embeddings   (trails truth = lazy embed, normal)"
log "layer 2  queue adds / deletes    : $q_adds / $q_dels   (chroma_introspect_ok=$chroma_ok)"
log "knowledge bases / files          : $kb / $kbf  (re-embed on next access if we nuke)"

# ── decide whether drift is CONFIRMED
#    signal = uncompacted delete-tombstones in the memory collection's queue.
#    those are exactly the "deleted from UI but still retrievable" ghosts.
drift=false
reason=""
if [[ "$chroma_ok" == true ]]; then
	if (( q_dels > 0 )); then
		drift=true
		reason="$q_dels uncompacted delete-tombstone(s) in memory queue → ghost residue retrieval can still surface"
	fi
else
	log "⚠ could not resolve the memory collection / queue this chroma version."
	log "  run once with --check and paste output so the detector can be made exact."
fi

do_nuke() {
	if owui_running; then
		log "⛔ owui is RUNNING — refusing to nuke a live vector store (corruption risk)."
		log "   stop it via Launcher, then:  ./petal-ghost-check.sh --force"
		return 1
	fi
	local bak="$VECTOR_DB.bak-$(date +%Y%m%d-%H%M%S)"
	log "🌸 backing up  $VECTOR_DB  →  $bak"
	cp -r "$VECTOR_DB" "$bak"
	log "🔪 nuking vector store — owui will lazy-rebuild from the memory table on next start"
	rm -rf "$VECTOR_DB"
	log "✅ exorcism complete. ghost starved. (backup kept at $bak)"
	[[ "$kb" != 0 || "$kbf" != 0 ]] && log "ℹ note: $kb kb / $kbf files will re-embed on next access."
	return 0
}

case "$MODE" in
	--check)
		if [[ "$drift" == true ]]; then
			log "👁 DRIFT DETECTED: $reason"
			log "   (check mode — no disk touched. heal with: stop owui → ./petal-ghost-check.sh --force)"
		else
			log "🌷 no confirmed drift. clean, or chroma not introspectable (see above)."
		fi
		;;
	--force)
		log "💥 --force: healing regardless of drift signal"
		do_nuke || true
		;;
	auto|*)
		if [[ "$drift" == true ]]; then
			log "👁 DRIFT DETECTED: $reason — auto-healing"
			do_nuke || true
		else
			log "🌷 no confirmed drift — nothing to do (this is the good outcome)"
		fi
		;;
esac

log "── done ──"
