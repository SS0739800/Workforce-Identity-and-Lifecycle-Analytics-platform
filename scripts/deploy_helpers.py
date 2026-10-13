"""Small helpers shared by the deploy scripts (azure_deploy.py, aws_deploy.py)."""

import ipaddress
import urllib.request


class DeployError(Exception):
    pass


def as_cidr(ip_text: str) -> str:
    """'203.0.113.7\\n' -> '203.0.113.7/32'. Only a single public IPv4 address is accepted."""
    address = ipaddress.ip_address(ip_text.strip())
    if address.version != 4 or not address.is_global:
        raise DeployError(f"Expected a public IPv4 address, got {address}")
    return f"{address}/32"


def my_public_cidr() -> str:
    """Your current public IP as a /32, used to restrict who can open the console."""
    with urllib.request.urlopen("https://checkip.amazonaws.com", timeout=10) as response:
        return as_cidr(response.read().decode())
