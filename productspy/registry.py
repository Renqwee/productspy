from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Iterator, Type

from .exceptions import UnsupportedSiteError

if TYPE_CHECKING:
    from .base import BaseTracker

_REGISTRY: dict[str, Type["BaseTracker"]] = {}


def register(*patterns: str) -> Callable[[Type["BaseTracker"]], Type["BaseTracker"]]:
    """Class decorator: bind a tracker to one or more domain patterns.

    Two pattern shapes:
      "noon.com"  — exact host, or any subdomain of it.
      "amazon."   — trailing dot means "this label, any TLD":
                    amazon.sa, amazon.co.uk, smile.amazon.com.

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


def _pattern_matches(pattern: str, domain: str) -> bool:
    """Match on label boundaries, never on a bare substring.

    A plain `pattern in domain` test hands every one of these to the
    Noon tracker: fakenoon.com, noon.com.attacker.net, mynoon.com.sa.
    The first is someone else's shop, the third is a phishing host — and
    the tracker would happily fetch and parse both.
    """
    if pattern.endswith("."):
        # "amazon." -> the stem must be a whole label of the host.
        return pattern[:-1] in domain.split(".")
    return domain == pattern or domain.endswith("." + pattern)


def resolve_tracker(domain: str) -> Type["BaseTracker"]:
    """Longest matching pattern wins, so 'amazon.sa' beats 'amazon.'."""
    domain = (domain or "").lower().strip(".")
    matches = [(p, c) for p, c in _REGISTRY.items() if _pattern_matches(p, domain)]
    if not matches:
        raise UnsupportedSiteError(
            f"No tracker registered for domain: {domain}. "
            f"Registered patterns: {', '.join(sorted(_REGISTRY))}"
        )
    return max(matches, key=lambda item: len(item[0]))[1]


def supported_sites() -> set[str]:
    return {cls.site_name for cls in _REGISTRY.values()}


def iter_registry() -> Iterator[tuple[str, Type["BaseTracker"]]]:
    return iter(sorted(_REGISTRY.items()))