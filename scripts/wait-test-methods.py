"""Wait for actual method HTTP readiness, not just container start."""
import time
import httpx

for method, port in [('dowser', 58001), ('gctree', 58002), ('brepphylo', 58003), ('clonaltree', 58004)]:
    deadline = time.monotonic() + 180
    while True:
        try:
            response = httpx.get(f'http://127.0.0.1:{port}/spec', timeout=3, trust_env=False)
            response.raise_for_status()
            break
        except (httpx.HTTPError, OSError):
            if time.monotonic() >= deadline:
                raise RuntimeError(f'{method} never became ready')
            time.sleep(0.5)
    print(f'{method} ready', flush=True)
