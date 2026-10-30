from pathlib import Path

from src.services.jobs import pick_send_paths


def test_pick_send_paths_prefers_double_compress(tmp_path: Path):
    (tmp_path / "a.jpg").write_bytes(b"1")
    (tmp_path / "a_c.jpg").write_bytes(b"22")
    (tmp_path / "a_c_c.jpg").write_bytes(b"333")
    picked = pick_send_paths(tmp_path)
    assert [p.name for p in picked] == ["a_c_c.jpg"]


def test_pick_send_paths_falls_back_to_single_c(tmp_path: Path):
    (tmp_path / "scan.pdf").write_bytes(b"pdf")
    (tmp_path / "scan_c.pdf").write_bytes(b"small")
    picked = pick_send_paths(tmp_path)
    assert [p.name for p in picked] == ["scan_c.pdf"]
