#!/usr/bin/env bash
# 🌸 petal · hush — ask Petal for fresh empty-field whispers.
#   ./petal-hush.sh            new season (replaces petal's pool, keeps yours)
#   ./petal-hush.sh --keep     add to her pool
#   ./petal-hush.sh --dry      taste without planting
# point it elsewhere with PETAL_HUSH_URL / PETAL_HUSH_MODEL.
cd "$(dirname "$0")" && exec nice -n 10 python3 petal-hush.py "$@"
