"""The demo is the first thing anyone runs. If it breaks, the project looks dead."""
from agentattest import demo


def test_the_demo_runs_clean(capsys):
    assert demo.main() == 0
    out = capsys.readouterr().out
    # It must actually demonstrate a refusal, not just print prose about one.
    assert "REFUSED (exit 2)" in out
    assert "allowed (exit 0)" in out
    assert "UNKNOWN is not a pass" in out


def test_the_demo_shows_a_gate_being_rejected_at_construction(capsys):
    demo.main()
    out = capsys.readouterr().out
    assert "refused at construction" in out
    assert "THIS SHOULD NOT HAPPEN" not in out


def test_the_never_fails_gate_really_cannot_be_used():
    """The demo's own prop must behave the way the demo claims it does."""
    import pytest
    from agentattest import SelftestError

    with pytest.raises(SelftestError):
        demo.NeverFails().check("obviously bad")


def test_the_demo_checks_all_done_against_the_list(capsys):
    demo.main()
    out = capsys.readouterr().out
    assert '"All done" is checked against what was actually asked' in out
    assert "item(s) are open -- 2a: update the changelog" in out
    assert "the same claim passes, because now it is true" in out
