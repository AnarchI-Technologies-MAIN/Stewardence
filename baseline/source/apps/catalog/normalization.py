from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import idna

NORMALIZATION_VERSION = "AL-ID-1"
ASCII_WHITESPACE = " \t\r\n\f\v"


class IdentifierNormalizationError(ValueError):
    pass


def normalize_opaque_identifier(raw: str) -> str:
    value = raw.strip(ASCII_WHITESPACE)
    if not value:
        raise IdentifierNormalizationError("Identifier is empty")
    return value


def normalize_microsoft_app_id(raw: str) -> str:
    try:
        return str(UUID(normalize_opaque_identifier(raw)))
    except ValueError as error:
        raise IdentifierNormalizationError(
            "Invalid Microsoft application ID"
        ) from error


def normalize_hostname(raw: str) -> str:
    value = normalize_opaque_identifier(raw)
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlsplit(value)
    if not parsed.hostname:
        raise IdentifierNormalizationError("Hostname is missing")
    return _normalize_parsed_hostname(parsed.hostname)


def _normalize_parsed_hostname(raw_hostname: str) -> str:
    host = raw_hostname.rstrip(".")
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        pass
    try:
        ascii_host = idna.encode(
            host,
            uts46=True,
            std3_rules=True,
            transitional=False,
        ).decode("ascii")
    except idna.IDNAError as error:
        raise IdentifierNormalizationError("Invalid hostname") from error
    return ascii_host.lower()


def _network_location(hostname: str, port: int) -> str:
    rendered_host = f"[{hostname}]" if ":" in hostname else hostname
    return f"{rendered_host}:{port}"


def _parsed_http_url(raw: str):
    value = normalize_opaque_identifier(raw)
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.hostname:
        raise IdentifierNormalizationError("A complete HTTP or HTTPS URL is required")
    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError as error:
        raise IdentifierNormalizationError("Invalid URL port") from error
    return parsed, scheme, _normalize_parsed_hostname(parsed.hostname), port


def normalize_origin(raw: str) -> str:
    _parsed, scheme, hostname, port = _parsed_http_url(raw)
    return f"{scheme}://{_network_location(hostname, port)}"


def normalize_redirect_uri(raw: str) -> str:
    parsed, scheme, hostname, port = _parsed_http_url(raw)
    return urlunsplit(
        (
            scheme,
            _network_location(hostname, port),
            parsed.path,
            parsed.query,
            "",
        )
    )


def normalize_product_name(raw: str) -> str:
    value = normalize_opaque_identifier(raw)
    return re.sub(r"\s+", " ", value).casefold()


def canonicalize(identifier_type: str, raw: str) -> str:
    normalizers = {
        "microsoft_app_id": normalize_microsoft_app_id,
        "google_client_id": normalize_opaque_identifier,
        "oauth_client_id": normalize_opaque_identifier,
        "hostname": normalize_hostname,
        "domain": normalize_hostname,
        "origin": normalize_origin,
        "redirect_uri": normalize_redirect_uri,
        "product_name": normalize_product_name,
    }
    try:
        normalizer = normalizers[identifier_type]
    except KeyError as error:
        raise IdentifierNormalizationError("Unsupported identifier type") from error
    return normalizer(raw)
