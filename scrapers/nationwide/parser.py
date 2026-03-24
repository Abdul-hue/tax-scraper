from .models import NationwideResult


def parse_results(dts, dds, description: str) -> NationwideResult:
    """
    Map extracted <dt>/<dd> text and description into a NationwideResult.
    """
    from_label = dts[0].strip() if len(dts) > 0 else ""
    from_value = dds[0].strip() if len(dds) > 0 else ""
    to_label = dts[1].strip() if len(dts) > 1 else ""
    to_value = dds[1].strip() if len(dds) > 1 else ""
    percentage_change = dds[2].strip() if len(dds) > 2 else ""
    desc = description.strip() if description else ""

    error = None
    if not (from_label or to_label or percentage_change):
        error = "No results found"

    return NationwideResult(
        from_label=from_label,
        from_value=from_value,
        to_label=to_label,
        to_value=to_value,
        percentage_change=percentage_change,
        description=desc,
        error=error,
    )
