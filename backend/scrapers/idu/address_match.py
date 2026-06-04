from __future__ import annotations


class NoAddressMatchError(Exception):
    """Raised when house cannot be matched to a unique link in IDU's #addressmatch list."""
    pass


def _token_match(config_tok: str, link_tok: str) -> bool:
    """True when link_tok satisfies config_tok under the alphanumeric-suffix rule.

    Exact match always wins.  Otherwise link_tok must start with config_tok and
    the remainder must be purely alphabetic (no digits allowed in the suffix).

    Examples
    --------
    "1"  vs "1"   -> True   (exact)
    "1"  vs "10"  -> False  (suffix "0" is a digit)
    "1"  vs "1A"  -> True   (suffix "A" is alpha)
    "7"  vs "70"  -> False  (suffix "0" is a digit)
    "7"  vs "7B"  -> True   (suffix "B" is alpha)
    "36" vs "36A" -> True   (suffix "A" is alpha)
    """
    if link_tok == config_tok:
        return True
    if link_tok.startswith(config_tok):
        suffix = link_tok[len(config_tok):]
        if suffix and suffix.isalpha():
            return True
    return False


def _link_house_matches_config(config_house: str, link_house: str) -> bool:
    """True when every config_house token appears as an in-order subsequence of
    link_house tokens, each satisfied by the alphanumeric-suffix rule.

    Both arguments must already be upper-cased and stripped.

    Examples
    --------
    config="7"      link="FLAT 7"   -> True
    config="FLAT 7" link="FLAT 70"  -> False
    config="1"      link="10"       -> False
    config="1"      link="1A"       -> True
    """
    config_tokens = config_house.split()
    link_tokens = link_house.split()

    li = 0
    for ct in config_tokens:
        while li < len(link_tokens) and not _token_match(ct, link_tokens[li]):
            li += 1
        if li >= len(link_tokens):
            return False
        li += 1
    return True


def match_address_link(house: str, links: list) -> tuple:
    """Return ``(index, link)`` for the best match of *house* in *links*.

    Each link dict must have a ``"text"`` key whose value follows IDU's
    ``"<house>, <street>, <town>"`` address format.  The house segment is
    everything before the first comma.

    Matching priority
    -----------------
    1. Exact match on the normalised house segment.
    2. Token match with the alphanumeric-suffix rule (see :func:`_token_match`).
    3. Among token-matches pick the one with the *shortest* house segment (most
       specific).  An equal-length tie is treated as ambiguous → raises error.

    Raises
    ------
    NoAddressMatchError
        Zero matches found, or an ambiguous equal-length tie.
    """
    config_house = house.strip().upper()

    # Step 2 — exact match on the normalised house segment
    for idx, link in enumerate(links):
        link_house = link["text"].split(",")[0].strip().upper()
        if link_house == config_house:
            return idx, link

    # Step 3 — token match with alphanumeric-suffix rule
    candidates: list[tuple[int, dict, str]] = []
    for idx, link in enumerate(links):
        link_house = link["text"].split(",")[0].strip().upper()
        if _link_house_matches_config(config_house, link_house):
            candidates.append((idx, link, link_house))

    if not candidates:
        available = [lnk["text"] for lnk in links]
        raise NoAddressMatchError(
            f"Could not find '{house}' in address list. "
            f"Available options: {available}"
        )

    # Step 4 — shortest house segment wins; equal-length tie → ambiguous error
    min_len = min(len(c[2]) for c in candidates)
    shortest = [c for c in candidates if len(c[2]) == min_len]

    if len(shortest) > 1:
        available = [lnk["text"] for lnk in links]
        raise NoAddressMatchError(
            f"Ambiguous match for '{house}': candidates {[c[2] for c in shortest]} "
            f"have equal-length house segments. "
            f"Specify the full value (e.g. '2A') to disambiguate. "
            f"Available options: {available}"
        )

    best_idx, best_link, _ = shortest[0]
    return best_idx, best_link
