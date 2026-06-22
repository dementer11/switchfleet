from pathlib import Path


def test_vendor_support_matrix_exists_and_readme_links_to_it() -> None:
    root = Path(__file__).resolve().parents[2]
    matrix = root / "docs" / "vendor-support-matrix.md"
    readme = root / "README.md"

    matrix_text = matrix.read_text(encoding="utf-8")
    readme_text = readme.read_text(encoding="utf-8")

    assert "docs/vendor-support-matrix.md" in readme_text
    for family in (
        "Huawei VRP",
        "HPE / 3Com Comware",
        "QTECH",
        "Eltex MES",
        "Bulat",
        "Dell PowerConnect",
        "Cisco IOS",
        "D-Link unmanaged",
        "SecurityCode Continent",
        "ICMP / Unknown",
        "GenericSSH",
    ):
        assert family in matrix_text
    assert "Production apply remains disabled" in matrix_text
    assert "database-backed generic job `/run` path uses `DummyTransport`" in matrix_text
