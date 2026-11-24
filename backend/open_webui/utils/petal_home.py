"""🏡 the fork's one home (A42): Petal-App-Data/petal-open-webui/.

older fork code wrote under Petal-App-Data/open-webui/ (the harvests). at boot, settle() moves whatever is still
there into petal-open-webui/, once:
  · never overwrites: on a name clash both are kept (the one from the old folder gains ' · from open-webui')
  · empty folders left behind are removed; a tiny README.md stays in the old folder, saying where things went
  · numbers only in the log (files moved, clashes kept), never a name
nothing to move (only the README, or no old folder): nothing happens.
"""

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

README = (
    '# moved\n\n'
    "everything the fork kept here now lives in `../petal-open-webui/` (the fork's one home, A42).\n"
    "a file whose name was already taken there was kept beside it, its name ending in ' · from open-webui'.\n"
)
TAG = ' · from open-webui'


def app_data() -> Path:
    return Path(os.environ.get('PETAL_APP_DATA') or '~/Gardens/Documents/Petal-App-Data').expanduser()


def home() -> Path:
    return app_data() / 'petal-open-webui'


def _free(dst: Path) -> Path:
    stem, suf = (dst.stem, dst.suffix) if dst.is_file() or dst.suffix else (dst.name, '')
    for i in range(1, 1000):
        cand = dst.with_name(f'{stem}{TAG}{"" if i == 1 else f" {i}"}{suf}')
        if not cand.exists():
            return cand
    raise FileExistsError(str(dst))


def settle(root: Path | None = None) -> dict:
    """the one-time move · → {moved, clashes} (numbers only)"""
    base = Path(root) if root else app_data()
    old, new = base / 'open-webui', base / 'petal-open-webui'
    out = {'moved': 0, 'clashes': 0}
    if not old.is_dir():
        return out
    files = [p for p in old.rglob('*') if (p.is_file() or p.is_symlink()) and p != old / 'README.md']
    if not files:
        return out
    new.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(new, 0o700)
    except OSError:
        pass
    for f in sorted(files):
        dst = new / f.relative_to(old)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists() or dst.is_symlink():
            dst = _free(dst)
            out['clashes'] += 1
        os.replace(f, dst)
        out['moved'] += 1
    for d in sorted((p for p in old.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    try:
        (old / 'README.md').write_text(README, encoding='utf-8')
    except OSError:
        pass
    log.info(f"🏡 the fork's home: {out['moved']} files moved from open-webui/ to petal-open-webui/ · {out['clashes']} clashes kept both")
    return out
