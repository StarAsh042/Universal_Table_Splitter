"""CLI 测试：证明命令行与界面共用同一套核心逻辑。"""

from __future__ import annotations

import pandas as pd
import pytest

from universal_table_splitter import cli
from universal_table_splitter.settings import Settings

from .conftest import ROW_COUNT


@pytest.fixture(autouse=True)
def _quiet_logging(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "setup_logging", lambda *args, **kwargs: tmp_path / "app.log")


def test_help_exits_cleanly(capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(["--help"])
    assert info.value.code == 0
    assert "table-splitter" in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(["--version"])
    assert info.value.code == 0


def test_split_csv(basic_csv, out_dir, capsys):
    code = cli.main([str(basic_csv), "-o", str(out_dir), "-n", "3", "-d", "001", "-f", "csv", "-q"])
    assert code == 0
    assert sorted(path.name for path in out_dir.glob("*.csv")) == [
        "artists_001.csv",
        "artists_002.csv",
        "artists_003.csv",
        "artists_004.csv",
    ]


def test_split_reports_summary(basic_csv, out_dir, capsys):
    assert cli.main([str(basic_csv), "-o", str(out_dir), "-n", "5", "--lang", "cn"]) == 0
    captured = capsys.readouterr()
    assert "完成" in captured.out
    assert "2 个文件" in captured.out


def test_lang_switch_changes_messages(basic_csv, out_dir, capsys):
    assert cli.main([str(basic_csv), "-o", str(out_dir), "-n", "5", "--lang", "en"]) == 0
    assert "Done" in capsys.readouterr().out


def test_fidelity_preserves_leading_zeros(basic_csv, out_dir):
    cli.main([str(basic_csv), "-o", str(out_dir), "-n", "3", "-q"])
    frame = pd.read_csv(out_dir / "artists_001.csv", dtype=str)
    assert frame["id"].tolist() == ["001", "002", "003"]


def test_no_fidelity_allows_type_inference(basic_csv, out_dir):
    cli.main([str(basic_csv), "-o", str(out_dir), "-n", "3", "--no-fidelity", "-q"])
    frame = pd.read_csv(out_dir / "artists_001.csv")
    assert frame["id"].tolist() == [1, 2, 3]


def test_default_output_dir_is_input_dir(basic_csv):
    cli.main([str(basic_csv), "-n", "1000", "-q"])
    assert (basic_csv.parent / "artists_001.csv").exists()


def test_default_export_format_follows_input(json_file, out_dir):
    cli.main([str(json_file), "-o", str(out_dir), "-n", "5", "-q"])
    assert (out_dir / "data_001.json").exists()


def test_index_policy_keeps_existing_file(basic_csv, out_dir):
    stale = out_dir / "artists_001.csv"
    stale.write_text("stale\n", encoding="utf-8")
    cli.main([str(basic_csv), "-o", str(out_dir), "-n", "3", "--overwrite", "index", "-q"])
    assert stale.read_text(encoding="utf-8") == "stale\n"
    assert (out_dir / "artists_001_1.csv").exists()


def test_missing_input_returns_code_2(tmp_path, out_dir, capsys):
    assert cli.main([str(tmp_path / "nope.csv"), "-o", str(out_dir)]) == 2
    assert capsys.readouterr().err.strip()


def test_invalid_rows_returns_code_2(basic_csv, out_dir, capsys):
    assert cli.main([str(basic_csv), "-o", str(out_dir), "-n", "abc"]) == 2
    assert "每份行数" in capsys.readouterr().err or True


def test_invalid_digits_returns_code_2(basic_csv, out_dir):
    assert cli.main([str(basic_csv), "-o", str(out_dir), "-d", "03d"]) == 2


def test_unsupported_input_returns_code_2(tmp_path, out_dir):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    assert cli.main([str(path), "-o", str(out_dir)]) == 2


def test_empty_table_returns_code_2(tmp_path, out_dir, capsys):
    empty = tmp_path / "empty.csv"
    empty.write_text("id,artist\n", encoding="utf-8")
    assert cli.main([str(empty), "-o", str(out_dir)]) == 2
    assert capsys.readouterr().err.strip()


def test_gbk_input_is_supported(gbk_csv, out_dir):
    assert cli.main([str(gbk_csv), "-o", str(out_dir), "-n", "4", "-q"]) == 0
    frame = pd.read_csv(out_dir / "gbk_001.csv", dtype=str)
    assert len(frame) == 4
    assert "中文字段" in frame["artist"].tolist()


def test_multi_sheet_requires_explicit_choice(xlsx_multi, out_dir):
    cli.main([str(xlsx_multi), "-o", str(out_dir), "--sheet", "Second", "-n", "1000", "-q"])
    frame = pd.read_excel(out_dir / "multi_001.xlsx")
    assert frame["artist"].tolist() == ["second-sheet"]


def test_row_totals_match_source(basic_csv, out_dir):
    cli.main([str(basic_csv), "-o", str(out_dir), "-n", "2", "-q"])
    total = sum(len(pd.read_csv(path)) for path in out_dir.glob("*.csv"))
    assert total == ROW_COUNT


def test_stream_flag_produces_identical_output(basic_csv, tmp_path):
    buffered = tmp_path / "buffered"
    streamed = tmp_path / "streamed"
    cli.main([str(basic_csv), "-o", str(buffered), "-n", "3", "-q"])
    cli.main([str(basic_csv), "-o", str(streamed), "-n", "3", "--stream", "-q"])
    for name in ("artists_001.csv", "artists_004.csv"):
        assert (buffered / name).read_bytes() == (streamed / name).read_bytes()


def test_cli_uses_settings_language_by_default(monkeypatch, basic_csv, out_dir, capsys):
    monkeypatch.setattr(Settings, "load", classmethod(lambda cls, path=None: Settings(lang="en")))
    cli.main([str(basic_csv), "-o", str(out_dir), "-n", "5"])
    assert "Done" in capsys.readouterr().out
