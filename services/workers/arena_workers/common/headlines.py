"""Template-driven daily headline (no LLM): spec 11.4."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Line:
    slug: str
    name: str
    ret: float
    today: float | None


def _pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def make_headline(lines: list[Line]) -> tuple[str, str]:
    """Returns (headline, deck) from leaderboard rows."""
    if not lines:
        return "THE FIELD LINES UP", "No results yet; the bots are at the gate."
    ranked = sorted(lines, key=lambda x: x.ret, reverse=True)
    lead, last = ranked[0], ranked[-1]
    short = {x.slug: x.name.removeprefix("The ").upper() for x in lines}
    movers = [x for x in lines if x.today is not None]
    if all(abs(x.today or 0) < 0.001 for x in movers) and len(movers) == len(lines):
        head = f"QUIET SESSION; {short[lead.slug]} HOLDS FIRM" if lead.slug == "index" else \
            f"QUIET SESSION; {short[lead.slug]} KEEPS THE LEAD"
        deck = f"{lead.name} leads at {_pct(lead.ret)}; the field is flat on the day."
        return head, deck
    best = max(movers, key=lambda x: x.today or 0.0)
    worst = min(movers, key=lambda x: x.today or 0.0)
    if lead.slug == "analyst":
        head = f"ANALYST TAKES THE LEAD AS {short[last.slug]} STUMBLES"
    elif (worst.today or 0) < -0.005 and worst.slug != lead.slug:
        head = f"{short[lead.slug]} LEADS AS {short[worst.slug]} STUMBLES"
    else:
        head = f"{short[best.slug]} POSTS BEST DAY AS {short[lead.slug]} LEADS" \
            if best.slug != lead.slug else f"{short[lead.slug]} EXTENDS ITS LEAD"
    if best.slug == lead.slug:
        deck = (f"{lead.name} leads at {_pct(lead.ret)} and is the day's best at {_pct(best.today or 0.0)}; "
                f"{worst.name} is the weakest at {_pct(worst.today or 0.0)}.")
    else:
        deck = (f"{lead.name} leads at {_pct(lead.ret)}. {best.name} is the day's best at "
                f"{_pct(best.today or 0.0)}; {worst.name} is the weakest at {_pct(worst.today or 0.0)}.")
    return head, deck
