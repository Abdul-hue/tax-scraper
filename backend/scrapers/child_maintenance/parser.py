from bs4 import BeautifulSoup


def parse_final_result(html: str) -> tuple[str, str]:
    """
    Extract the final calculator decision text and supporting reason from
    the GOV.UK child maintenance result page.
    """
    soup = BeautifulSoup(html, "html.parser")

    result = ""
    reason = ""

    panel_text = soup.select_one(".govuk-panel__body")
    if panel_text:
        result = panel_text.get_text(" ", strip=True)

    if not result:
        h1 = soup.select_one("h1")
        if h1:
            result = h1.get_text(" ", strip=True)

    if not reason:
        # Prefer lead paragraph style blocks.
        lead = soup.select_one(".govuk-body-l")
        if lead:
            reason = lead.get_text(" ", strip=True)

    if not reason:
        # Fallback: first meaningful paragraph not identical to result.
        for p in soup.select(".govuk-main-wrapper p, main p"):
            text = p.get_text(" ", strip=True)
            if text and text != result:
                reason = text
                break

    return result, reason
