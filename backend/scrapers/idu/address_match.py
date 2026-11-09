from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


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


def _by_whole_address(house: str, links: list, street: str) -> list:
    """Step 3: links that fit the case's WHOLE address, ranked by words shared.

    ⚠️ FOR WHAT A HOUSE SEGMENT CANNOT MATCH (2026-11-04): no house at all
    ("Rose Cottage Main Road" -- no comma, so the caller cannot tell the name
    from the street), or a house name TraceSmart writes differently. With no
    house the scraper used to submit the form with NO address picked, and
    TraceSmart never searched ("IDU results page did not render").

    A link fits only if BOTH hold, so it is never a guess at a neighbour:
      - every word of its house segment is in the case's address -- "ROSE
        VILLA" never stands in for Rose Cottage, nor "FLAT 1, ..." for a
        building whose flat the case does not give;
      - every word of the case's house is in the link -- "Flat 7" never takes
        "FLAT 17".
    """
    case_words = _words(_normalise_house(f"{house} {street}"))
    house_words = _words(_normalise_house(house))
    ranked = []
    for idx, link in enumerate(links):
        link_words = _words(_normalise_house(link["text"]))
        link_house = _words(_normalise_house(link["text"].split(",")[0]))
        if link_house and link_house <= case_words and house_words <= link_words:
            ranked.append((len(case_words & link_words), idx, link))
    return ranked


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
    3. Nothing matched the house -- or there is no house -- the whole address
       (:func:`_by_whole_address`), most words shared first.
    4. A flat or room TraceSmart does not list, in a building it does list
       with no flats at all: the building (:func:`_by_building`).
    5. A tie on all of that between different addresses is ambiguous -> error.
       Never a guess.

    Raises
    ------
    NoAddressMatchError
        Zero matches found, or an ambiguous tie.
    """
    config_house = _normalise_house(house or "")
    street_words = _words(street) - _words(config_house)

    # ⚠️ No house skips steps 1-2: an empty house "matches" every link there.
    if not config_house:
        return _whole_address_or_raise(house, links, street)

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
        return _whole_address_or_raise(house, links, street)
    return _pick(house, links, candidates)


#: Words that make the case's house PART of a building -- a flat, a room.
#: TraceSmart (Royal Mail's list) often holds the building and not its parts.
_SUB_PREMISE = {"FLAT", "ROOM", "STUDIO", "BEDSIT", "MAISONETTE", "ANNEXE", "UNIT"}

#: The last word of a street -- a building that is only a street ("Main Road")
#: is no building. Mirrors CAT's `platform/scrapers.py :: _STREET_WORDS`.
_STREET_WORDS = {
    "ROAD", "RD", "STREET", "ST", "LANE", "LN", "AVENUE", "AVE", "DRIVE", "DR",
    "CLOSE", "CRESCENT", "WAY", "GROVE", "PLACE", "TERRACE", "GARDENS",
    "SQUARE", "MEWS", "PARADE", "WALK", "ROW",
}


def _tokens(text: str) -> tuple:
    """The words of one address part, normalised: "St. Patricks Road" ->
    ("ST", "PATRICKS", "ROAD"); "Apartment 7" -> ("FLAT", "7")."""
    return tuple(re.findall(r"[A-Z0-9]+", _normalise_house(text or "")))


def _parts(text: str) -> list:
    return [t for t in (_tokens(p) for p in (text or "").split(",")) if t]


def _by_building(house: str, links: list, street: str) -> list:
    """Step 4: the case's FLAT or ROOM is not listed, but its BUILDING is.

    ⚠️ WHY (2026-11-10). 9 of staging's 74 failed IDU runs gave a flat or room
    TraceSmart does not hold, at a building it does: "Room 5, 14 Angel Place"
    (only "14 ANGEL PLACE"), "Flat C, 138 Merton Road" (only "138 MERTON
    ROAD"), "Flat 65, Bagshot Manor, 1 Green Lane" (only "BAGSHOT MANOR, 1
    GREEN LANE"). That building IS the client's postal address without the
    flat -- not a neighbour's. Agreed with the user 2026-11-10.

    A link is the building only if ALL hold, so it is never a guess:
      - the case's house is a part of a building (`_SUB_PREMISE`: "Flat 7",
        "Room 5", "Bottom Flat") -- a plain house never falls back;
      - the link BEGINS with the case's whole street, part for part ("14 ANGEL
        PLACE, WORCESTER" for "14 Angel Place"; "THE ANGEL, 14 ANGEL PLACE"
        does not, nor "3 TRESMERE COURT, VICTORIA ROAD" for "3 Victoria Road");
      - that street names a building -- a number, or a name that is not a
        street ("Main Road" alone picks nothing);
      - TraceSmart lists NO flat, room or unit in that building. If it lists
        some and not the case's, the case's flat is wrong -- an error, as
        before ("Flat 7" never falls back to a block holding FLAT 17 and 70).
    """
    if not (set(_tokens(house)) & _SUB_PREMISE):
        return []
    building = _parts(street)
    if not building:
        return []
    first = building[0]
    if not any(t[0].isdigit() for t in first) and first[-1] in _STREET_WORDS:
        return []
    n = len(building)
    ranked = []
    for idx, link in enumerate(links):
        parts = _parts(link["text"])
        if parts[:n] == building:
            ranked.append((-len(parts), idx, link))
        # A part of this building listed under it -> its flats are known.
        elif any(parts[i:i + n] == building and set(parts[i - 1]) & _SUB_PREMISE
                 for i in range(1, len(parts) - n + 1)):
            return []
    return ranked


def _whole_address_or_raise(house: str, links: list, street: str) -> tuple:
    """Step 3, step 4, or the error naming what TraceSmart offered -- the
    advisor fixes the House No/Name from it and re-runs."""
    ranked = _by_whole_address(house or "", links, street or "")
    if ranked:
        return _pick(house or street, links, ranked)
    ranked = _by_building(house or "", links, street or "")
    if ranked:
        # The same building listed twice ("6 CENTRIC CLOSE, OVAL ROAD, LONDON"
        # and "6 CENTRIC CLOSE, LONDON") is one address: the shortest is taken.
        ranked.sort(key=lambda r: (r[0], -r[1]), reverse=True)
        _, idx, link = ranked[0]
        logger.warning("IDU address: %r is not listed at the postcode; its building "
                       "%r is picked", house, link["text"])
        return idx, link
    available = [lnk["text"] for lnk in links]
    if not (house or "").strip():
        raise NoAddressMatchError(
            f"No house number or name was given, and the address '{street}' "
            f"does not single out one address at the postcode. Enter the "
            f"House No/Name and re-run. Available options: {available}"
        )
    raise NoAddressMatchError(
        f"Could not find '{house}' in address list. "
        f"Available options: {available}"
    )
