from arena_workers.common.headlines import Line, make_headline


def test_quiet_session() -> None:
    h, d = make_headline([Line("index", "The Index", 0.01, 0.0), Line("breakout", "The Breakout", 0.0, 0.0)])
    assert h == "QUIET SESSION; INDEX HOLDS FIRM" and "+1.00%" in d


def test_analyst_lead() -> None:
    h, _ = make_headline([Line("analyst", "The Analyst", 0.05, 0.01), Line("crossover", "The Crossover", -0.02, -0.02)])
    assert h == "ANALYST TAKES THE LEAD AS CROSSOVER STUMBLES"


def test_empty() -> None:
    assert make_headline([])[0] == "THE FIELD LINES UP"
