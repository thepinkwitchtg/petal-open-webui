"""
petal_skin_cache 🌸 — the petal skin always asks before it's reused.

OWUI serves /static with an ETag but no Cache-Control, so a browser picks its own heuristic
freshness and, on a normal reload, keeps serving an old theme.css without asking (found nov 6:
toasts.css was imported by a theme.css the PC never re-fetched, so toasts stayed sonner-black).

for the skin only (custom.css, loader.js, static/petal/* except the fonts) this adds
`Cache-Control: no-cache`: the browser keeps its copy but revalidates every load — a 304 when
nothing changed — so a full build or a --skin sync shows on the next ordinary reload, on every
device. pure ASGI (no BaseHTTPMiddleware), so streaming responses are never touched.
"""

SKIN_FILES = ('/static/custom.css', '/static/loader.js')
SKIN_DIR = '/static/petal/'
SKIN_SKIP = ('/static/petal/fonts/',)  # fonts never change in place: let them cache


def is_skin(path: str) -> bool:
    if path in SKIN_FILES:
        return True
    return path.startswith(SKIN_DIR) and not path.startswith(SKIN_SKIP)


class PetalSkinRevalidate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get('type') != 'http' or not is_skin(scope.get('path', '')):
            return await self.app(scope, receive, send)

        async def send_revalidating(message):
            if message.get('type') == 'http.response.start':
                headers = [(k, v) for k, v in message.get('headers', []) if k.lower() != b'cache-control']
                headers.append((b'cache-control', b'no-cache'))
                message = {**message, 'headers': headers}
            await send(message)

        await self.app(scope, receive, send_revalidating)
