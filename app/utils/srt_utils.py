"""
SRT Utility Functions

Helpers for building and validating SRT stream URLs for MediaMTX.
"""
from typing import Optional
from app.config import settings


def is_srt_url(url: str) -> bool:
    """
    Check if a URL is an SRT stream.

    Args:
        url: Stream URL to check

    Returns:
        True if URL starts with srt://
    """
    return url.startswith("srt://")


def build_srt_read_url(
    host: str,
    port: int = 8890,
    stream_id: str = "",
    latency_ms: Optional[int] = None,
    pkt_size: Optional[int] = None
) -> str:
    """
    Build an SRT URL for reading from MediaMTX.

    Uses settings from config.py for defaults.

    Args:
        host: MediaMTX server hostname or IP
        port: SRT port (default 8890)
        stream_id: MediaMTX stream path (e.g., "camera1")
        latency_ms: SRT latency in milliseconds (default from settings)
        pkt_size: SRT packet size (default from settings)

    Returns:
        Fully formed SRT URL with all parameters

    Example:
        >>> build_srt_read_url("192.168.1.100", stream_id="camera1")
        'srt://192.168.1.100:8890?streamid=read:camera1&latency=400000&pkt_size=1316'
    """
    latency_ms = latency_ms or settings.SRT_LATENCY_MS
    pkt_size = pkt_size or settings.SRT_PACKET_SIZE

    # FFmpeg expects latency in microseconds
    latency_us = latency_ms * 1000

    # Build URL with MediaMTX stream ID format
    url = f"srt://{host}:{port}"

    params = []
    if stream_id:
        params.append(f"streamid=read:{stream_id}")
    params.append(f"latency={latency_us}")
    params.append(f"pkt_size={pkt_size}")

    if params:
        url += "?" + "&".join(params)

    return url


def build_srt_publish_url(
    host: str,
    port: int = 8890,
    stream_id: str = "",
    latency_ms: Optional[int] = None,
    pkt_size: Optional[int] = None
) -> str:
    """
    Build an SRT URL for publishing to MediaMTX.

    Args:
        host: MediaMTX server hostname or IP
        port: SRT port (default 8890)
        stream_id: MediaMTX stream path (e.g., "camera1")
        latency_ms: SRT latency in milliseconds (default from settings)
        pkt_size: SRT packet size (default from settings)

    Returns:
        Fully formed SRT URL for publishing

    Example:
        >>> build_srt_publish_url("192.168.1.100", stream_id="camera1")
        'srt://192.168.1.100:8890?streamid=publish:camera1&latency=400000&pkt_size=1316'
    """
    latency_ms = latency_ms or settings.SRT_LATENCY_MS
    pkt_size = pkt_size or settings.SRT_PACKET_SIZE

    latency_us = latency_ms * 1000

    url = f"srt://{host}:{port}"

    params = []
    if stream_id:
        params.append(f"streamid=publish:{stream_id}")
    params.append(f"latency={latency_us}")
    params.append(f"pkt_size={pkt_size}")

    if params:
        url += "?" + "&".join(params)

    return url


def parse_srt_url(url: str) -> dict:
    """
    Parse an SRT URL into its components.

    Args:
        url: SRT URL to parse

    Returns:
        Dictionary with host, port, stream_id, latency_ms, pkt_size

    Example:
        >>> parse_srt_url("srt://192.168.1.100:8890?streamid=read:camera1&latency=400000")
        {'host': '192.168.1.100', 'port': 8890, 'stream_id': 'camera1', 'mode': 'read', 'latency_ms': 400, 'pkt_size': None}
    """
    if not is_srt_url(url):
        raise ValueError(f"Not an SRT URL: {url}")

    result = {
        "host": None,
        "port": 8890,
        "stream_id": None,
        "mode": None,
        "latency_ms": None,
        "pkt_size": None
    }

    # Remove srt:// prefix
    url = url[6:]

    # Split host:port from parameters
    if "?" in url:
        host_part, params_part = url.split("?", 1)
    else:
        host_part = url
        params_part = ""

    # Parse host and port
    if ":" in host_part:
        host, port = host_part.split(":", 1)
        result["host"] = host
        result["port"] = int(port)
    else:
        result["host"] = host_part

    # Parse query parameters
    if params_part:
        for param in params_part.split("&"):
            if "=" in param:
                key, value = param.split("=", 1)

                if key == "streamid":
                    # Parse mode:stream_id format
                    if ":" in value:
                        mode, stream_id = value.split(":", 1)
                        result["mode"] = mode
                        result["stream_id"] = stream_id
                    else:
                        result["stream_id"] = value

                elif key == "latency":
                    # Convert microseconds to milliseconds
                    result["latency_ms"] = int(value) // 1000

                elif key == "pkt_size":
                    result["pkt_size"] = int(value)

    return result
