"""`QualityProject` (project.py) is the seam a second backend plugs into.

Two things need proving, both directions, per the project's own standard for a
new check: that it recognises something that DOES satisfy the contract, and
that it refuses something that does not -- an interface only one side of which
is ever tested is not proven at all.
"""
from pathlib import Path

from deadcanary.hunt import DbtProject
from deadcanary.project import QualityProject


def test_dbtproject_satisfies_the_protocol(tmp_path):
    root = tmp_path / "proj"
    (root / "target").mkdir(parents=True)
    (root / "dbt_project.yml").write_text("name: fake\n", encoding="utf-8")
    import duckdb
    duckdb.connect(str(root / "w.duckdb")).close()

    assert isinstance(DbtProject(root), QualityProject), (
        "DbtProject is the class this Protocol was extracted from -- if this "
        "ever fails, the Protocol has drifted from the class it describes"
    )


def test_something_missing_the_contract_does_not_satisfy_it():
    class NotAProject:
        """Has a `root`, nothing else -- the shape a half-built adapter would
        have on its first day."""
        root = Path(".")

    assert not isinstance(NotAProject(), QualityProject), (
        "a class missing build()/run_and_test()/etc. must not pass — a "
        "Protocol that accepts anything proves nothing about the contract"
    )
