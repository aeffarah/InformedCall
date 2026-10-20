"""Turn Kalshi market metadata plus actual climate values into yes/no labels.

Used to check that our reading of each series' rules reproduces Kalshi's recorded results
before any of this feeds a model.
"""

import re

import pandas as pd

_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def event_date(event_ticker: str) -> pd.Timestamp:
    """KXHIGHNY-26AUG19 -> 2026-08-19."""
    return pd.to_datetime(event_ticker.split("-")[1], format="%y%b%d")


def parse_bracket(yes_sub_title: str) -> tuple[str | None, float | None, float | None]:
    """Parse a high-temp subtitle like '87° or higher' into (kind, low, high).

    kind is 'ge' (>= low), 'le' (<= low), or 'between' (low <= x <= high). Legacy markets use
    half-degree thresholds ('51.5° or higher'), which plain comparisons handle because the
    reported high is a whole number.
    """
    text = str(yes_sub_title).replace("�", "").replace("°", "")
    nums = [float(n) for n in _NUMBER.findall(text)]
    if not nums:
        return None, None, None
    if re.search(r"or (above|higher)", text):
        return "ge", nums[0], None
    if re.search(r"or (below|lower)", text):
        return "le", nums[0], None
    if " to " in text and len(nums) == 2:
        return "between", nums[0], nums[1]
    return None, None, None


def bracket_yes(high: float, kind: str | None, low: float | None, top: float | None) -> bool | None:
    if pd.isna(high) or kind is None:
        return None
    if kind == "ge":
        return high >= low
    if kind == "le":
        return high <= low
    return low <= high <= top


def rain_yes(precip: float | None, trace: bool, threshold: float, trace_counts: bool) -> bool | None:
    """Whether precipitation exceeds the threshold.

    The older KXRAINNYC series resolved a trace as rain; the newer KXRAIN series counts it as
    0 inches. Pass trace_counts accordingly.
    """
    if trace:
        return trace_counts and threshold == 0
    if precip is None or pd.isna(precip):
        return None
    return precip > threshold
