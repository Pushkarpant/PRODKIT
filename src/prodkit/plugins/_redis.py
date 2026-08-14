"""Shared Redis client construction for plugins with a Redis backend.

The optional ``redis`` dependency is imported lazily here — plugin modules are
imported unconditionally by ``prodkit.plugins``, so a missing extra must not
break ``import prodkit``. It fails at plugin ``configure()`` time instead, with
an actionable message. This function is also the single seam tests monkeypatch
to inject a fake client (fakeredis).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from prodkit.core.exceptions import ProdKitConfigError

if TYPE_CHECKING:
    from redis.asyncio import Redis


def create_client(url: str, *, section: str = "redis") -> Redis:
    """Create an async Redis client, or fail with a named-section pip hint.

    The client connects lazily (on first command), so calling this at boot is
    cheap; reachability is verified by the owning plugin's ``startup()`` ping.
    """
    try:
        from redis.asyncio import Redis
    except ImportError:
        raise ProdKitConfigError(
            f"{section}: backend='redis' requires the redis package. "
            "Install it with: pip install 'prodkit[redis]'"
        ) from None
    client: Any = Redis.from_url(url)
    return client  # type: ignore[no-any-return]
