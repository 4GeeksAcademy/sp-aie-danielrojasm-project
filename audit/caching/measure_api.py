"""Mide la latencia de los GET de la API con peticiones repetidas.

Uso (con la API ya arrancada y un usuario que pueda iniciar sesión):

    uv run python audit/caching/measure_api.py --base-url http://127.0.0.1:8000 \\
        --email medicion@example.com --password <contraseña> --runs 30 --label before

Si el usuario no existe, lo registra con `POST /users`. Cada endpoint se pide
`--runs` veces seguidas con la misma URL (el patrón de ráfaga que se busca en
los logs) y se guarda la mediana y el p95 de dos tiempos:

- `server_ms`: cabecera `Server-Timing` del middleware (coste dentro de la API).
- `client_ms`: ida y vuelta completa medida desde el cliente.

La primera petición de cada endpoint se descarta como calentamiento. El
resultado va a `audit/caching/results/<label>.json` y a la consola.
"""

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path


RESULTS_DIR = Path(__file__).with_name("results")
ENDPOINTS = [
    "/",
    "/auth/me",
    "/profiles/me",
    "/suppliers",
    "/api/incidents",
    "/api/incidents/summary",
    "/api/incidents/1",
    "/inventory/products",
    "/inventory/products?warehouse=LA",
    "/inventory/products/1",
    "/inventory/orders",
]


def _request(url: str, *, token: str | None = None, body: dict | None = None) -> tuple[int, dict, bytes]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method="POST" if data else "GET")
    if data:
        request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def _token(base_url: str, email: str, password: str) -> str:
    status, _, payload = _request(f"{base_url}/auth/login", body={"email": email, "password": password})
    if status == 401:
        _request(f"{base_url}/users", body={"email": email, "password": password})
        status, _, payload = _request(f"{base_url}/auth/login", body={"email": email, "password": password})
    if status != 200:
        raise SystemExit(f"No se pudo iniciar sesión ({status}).")
    return json.loads(payload)["access_token"]


def _server_ms(headers: dict) -> float | None:
    value = headers.get("Server-Timing") or headers.get("server-timing") or ""
    for part in value.split(";"):
        if part.startswith("dur="):
            return float(part[4:])
    return None


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]


def measure(base_url: str, token: str, path: str, runs: int) -> dict:
    server, client, sizes, status = [], [], [], None
    for attempt in range(runs + 1):
        start = time.perf_counter()
        status, headers, payload = _request(f"{base_url}{path}", token=token)
        elapsed = (time.perf_counter() - start) * 1000
        if attempt == 0:
            continue  # calentamiento: primera conexión, imports perezosos, pool vacío
        client.append(elapsed)
        server_value = _server_ms(headers)
        if server_value is not None:
            server.append(server_value)
        sizes.append(len(payload))
    return {
        "path": path,
        "status": status,
        "runs": runs,
        "bytes": sizes[-1] if sizes else 0,
        "server_ms_median": round(statistics.median(server), 1) if server else None,
        "server_ms_p95": round(_p95(server), 1) if server else None,
        "client_ms_median": round(statistics.median(client), 1),
        "client_ms_p95": round(_p95(client), 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--label", required=True, help="Nombre del fichero de resultados.")
    parser.add_argument("--note", default="", help="Contexto de la medición (base de datos, volumen).")
    parser.add_argument("--only", nargs="*", help="Medir solo estas rutas.")
    args = parser.parse_args()

    token = _token(args.base_url, args.email, args.password)
    results = [measure(args.base_url, token, path, args.runs) for path in (args.only or ENDPOINTS)]

    print(f"{'endpoint':38} {'st':>3} {'bytes':>9} {'srv p50':>8} {'srv p95':>8} {'cli p50':>8} {'cli p95':>8}")
    for row in results:
        print(
            f"{row['path']:38} {row['status']:>3} {row['bytes']:>9} "
            f"{row['server_ms_median']!s:>8} {row['server_ms_p95']!s:>8} "
            f"{row['client_ms_median']:>8} {row['client_ms_p95']:>8}"
        )
    RESULTS_DIR.mkdir(exist_ok=True)
    output = RESULTS_DIR / f"{args.label}.json"
    output.write_text(
        json.dumps({"label": args.label, "note": args.note, "results": results}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Resultados en {output.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
