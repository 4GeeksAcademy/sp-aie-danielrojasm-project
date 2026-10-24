"""`docker-compose.yml` no publica ningún puerto en todas las interfaces.

Docker escribe sus propias reglas de iptables y un puerto publicado como `"8000:8000"` queda abierto a internet
aunque UFW lo bloquee. Todo puerto tiene que ir atado a `127.0.0.1`; lo público entra por el proxy HTTPS del host.
"""

from pathlib import Path

import yaml


COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
LOOPBACK = "127.0.0.1"


def published_ports() -> list[tuple[str, str]]:
    services = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))["services"]
    return [(name, str(port)) for name, service in services.items() for port in service.get("ports", [])]


def test_every_published_port_is_bound_to_loopback():
    exposed = [(name, port) for name, port in published_ports() if not port.startswith(f"{LOOPBACK}:")]

    assert exposed == []


def test_the_services_that_used_to_listen_on_all_interfaces_are_still_published():
    ports = dict(published_ports())

    assert ports["api"] == "127.0.0.1:8000:8000"
    assert ports["mcp"] == "127.0.0.1:8001:8001"
