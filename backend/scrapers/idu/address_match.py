from __future__ import annotations

import re


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


#: Words for the same thing: a flat. TraceSmart lists a flat as "FLAT 7" or
#: "APARTMENT 7"; the case may say either, or "Apt 7". Compared as one word.
_FLAT_SYNONYMS = {"APARTMENT": "FLAT", "APT": "FLAT", "FLT": "FLAT"}


def _normalise_house(text: str) -> str:
    """Upper-cased, dots dropped, flat synonyms folded to FLAT."""
    tokens = text.replace(".", " ").upper().split()
    return " ".join(_FLAT_SYNONYMS.get(t, t) for t in tokens)


def _words(text: str) -> set:
    """The alphanumeric words of an address, upper-cased ("46", "FOO", ...)."""
    return set(re.findall(r"[A-Z0-9]+", (text or "").upper()))


def _starts_with_number(config_house: str, link_house: str) -> bool:
    """A plain house number ("7") that begins the link's house segment
    ("7 MAIN ROAD") -- not one found after a flat word ("FLAT 7")."""
    config_tokens, link_tokens = config_house.split(), link_house.split()
    return (len(config_tokens) == 1 and bool(link_tokens)
            and _token_match(config_tokens[0], link_tokens[0]))


def _pick(house: str, links: list, ranked: list) -> tuple:
    """The top of *ranked* (score, idx, link), or an error on a real tie.
    Two tied links with the SAME text are one address listed twice."""
    ranked.sort(key=lambda r: r[0], reverse=True)
    top = [r for r in ranked if r[0] == ranked[0][0]]
    if len({r[2]["text"].strip().upper() for r in top}) > 1:
        raise NoAddressMatchError(
            f"Ambiguous match for '{house}': {[r[2]['text'] for r in top]} fit "
            f"equally well. Check the flat / house number and street on the case. "
            f"Available options: {[lnk['text'] for lnk in links]}"
        )
    _, idx, link = top[0]
    return idx, link


def match_address_link(house: str, links: list, street: str = "") -> tuple:
    """Return ``(index, link)`` for the best match of *house* in *links*.

    Each link dict must have a ``"text"`` key whose value follows IDU's
    ``"<house>, <street>, <town>"`` address format.  The house segment is
    everything before the first comma.

    *street* is the rest of the case's address ("44 Foo Street", "Ferry
    House, Main Road"). It tells apart addresses whose house segment is the
    same -- ⚠️ one postcode can hold FLAT 7 in two buildings, and matching on
    "FLAT 7" alone took the first one listed, the wrong building half the time.

    Matching priority
    -----------------
    1. Exact match on the normalised house segment ("APARTMENT"/"APT" count as
       "FLAT"). Several exact matches: the one sharing the most *street* words.
    2. Otherwise a token match with the alphanumeric-suffix rule (see
       :func:`_token_match`), ranked by: most *street* words shared; then a
       plain house number that BEGINS the house segment ("7" -> "7 MAIN
       ROAD" over "FLAT 7"); then the *shortest* house segment.
    3. A tie on all of that between different addresses is ambiguous -> error.
       Never a guess.

    Raises
    ------
    NoAddressMatchError
        Zero matches found, or an ambiguous tie.
    """
    config_house = _normalise_house(house)
    street_words = _words(street) - _words(config_house)

    def street_score(link):
        return len(street_words & _words(link["text"]))

    houses = [(idx, link, _normalise_house(link["text"].split(",")[0]))
              for idx, link in enumerate(links)]

    # Step 1 — exact match on the normalised house segment
    exact = [(street_score(link), idx, link) for idx, link, link_house in houses
             if link_house == config_house]
    if exact:
        return _pick(house, links, exact)

    # Step 2 — token match with alphanumeric-suffix rule
    candidates = [
        ((street_score(link), _starts_with_number(config_house, link_house), -len(link_house)),
         idx, link)
        for idx, link, link_house in houses
        if _link_house_matches_config(config_house, link_house)
    ]
    if not candidates:
        available = [lnk["text"] for lnk in links]
        raise NoAddressMatchError(
            f"Could not find '{house}' in address list. "
            f"Available options: {available}"
        )
    return _pick(house, links, candidates)
