from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Iterator, Type

from .exceptions import UnsupportedSiteError

if TYPE_CHECKING:
    from .base import BaseTracker

_REGISTRY: dict[str, Type["BaseTracker"]] = {}


def register(*patterns: str) -> Callable[[Type["BaseTracker"]], Type["BaseTracker"]]:
    """Class decorator: bind a tracker to one or more domain fragments.

    @register("amazon.", "amzn.to")
    class AmazonTracker(BaseTracker): ...

    Adding a new store = one new file + this decorator. No core edits.
    """

    def decorator(cls: Type["BaseTracker"]) -> Type["BaseTracker"]:
        for pattern in patterns:
            key = pattern.lower()
            if key in _REGISTRY and _REGISTRY[key] is not cls:
                raise ValueError(
                    f"Pattern {key!r} already registered to "
                    f"{_REGISTRY[key].__name__}."
                )
            _REGISTRY[key] = cls
        return cls

    return decorator


def resolve_tracker(domain: str) -> Type["BaseTracker"]:
    """Longest-match wins, so 'amazon.sa' beats a generic 'amazon.'."""
    domain = domain.lower()
    matches = [(p, c) for p, c in _REGISTRY.items() if p in domain]
    if not matches:
        raise UnsupportedSiteError(
            f"No tracker registered for domain: {domain}. "
            f"Supported: {', '.join(sorted(supported_sites()))}"
        )
    return max(matches, key=lambda item: len(item[0]))[1]


def supported_sites() -> set[str]:
    return {cls.site_name for cls in _REGISTRY.values()}


def iter_registry() -> Iterator[tuple[str, Type["BaseTracker"]]]:
    return iter(sorted(_REGISTRY.items()))