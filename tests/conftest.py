"""共享测试夹具。

刻意包含"容易让分割器出错"的数据特征：
- 前导零 ID（``001``）—— 类型推断会把它变成 ``1``；
- 超长整数（``9007199254740993``）—— 会丢精度；
- 字段内含逗号/双引号/中文；
- 以 ``=`` 开头的单元格（Excel 公式注入向量）。
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pytest

HEADER = ("id", "artist", "count", "note")

ROWS: tuple[tuple[str, ...], ...] = (
    ("001", "hammer_(sunset_beach)", "82834", "ok"),
    ("002", "ebifurya", "5846", "comma,here"),
    ("003", "中文字段", "5387", 'quote"inside'),
    ("004", "a", "5229", "=1+1"),
    ("005", "b", "4512", "plain"),
    ("006", "c", "4291", "plain"),
    ("007", "d", "4269", "plain"),
    ("008", "e", "3890", "long 9007199254740993"),
    ("009", "f", "3807", "plain"),
    ("010", "g", "3748", "plain"),
)

ROW_COUNT = len(ROWS)


def _write_csv(path: Path, rows, encoding: str, delimiter: str = ",") -> Path:
    with path.open("w", encoding=encoding, newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter)
        writer.writerow(HEADER)
        writer.writerows(rows)
    return path


@pytest.fixture
def basic_csv(tmp_path: Path) -> Path:
    """UTF-8（无 BOM）标准 CSV，10 行数据。"""
    return _write_csv(tmp_path / "artists.csv", ROWS, "utf-8")


@pytest.fixture
def bom_csv(tmp_path: Path) -> Path:
    return _write_csv(tmp_path / "bom.csv", ROWS, "utf-8-sig")


@pytest.fixture
def gbk_csv(tmp_path: Path) -> Path:
    """中文 Windows 上最常见的"导出即 GBK"场景。"""
    return _write_csv(tmp_path / "gbk.csv", ROWS, "gbk")


@pytest.fixture
def semicolon_csv(tmp_path: Path) -> Path:
    """默认分隔符缺失时应能嗅探出 ``;``。"""
    return _write_csv(tmp_path / "euro.csv", ROWS, "utf-8", delimiter=";")


@pytest.fixture
def tsv_file(tmp_path: Path) -> Path:
    return _write_csv(tmp_path / "data.tsv", ROWS, "utf-8", delimiter="\t")


@pytest.fixture
def json_file(tmp_path: Path) -> Path:
    frame = pd.DataFrame(list(ROWS), columns=list(HEADER))
    path = tmp_path / "data.json"
    path.write_text(
        json.dumps(frame.to_dict(orient="records"), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def jsonl_file(tmp_path: Path) -> Path:
    frame = pd.DataFrame(list(ROWS), columns=list(HEADER))
    path = tmp_path / "data.jsonl"
    lines = [json.dumps(record, ensure_ascii=False) for record in frame.to_dict(orient="records")]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.fixture
def xlsx_single(tmp_path: Path) -> Path:
    path = tmp_path / "single.xlsx"
    pd.DataFrame(list(ROWS), columns=list(HEADER)).to_excel(path, index=False, engine="openpyxl")
    return path


@pytest.fixture
def xlsx_multi(tmp_path: Path) -> Path:
    """多工作表：用于验证"只读第一个 sheet"这一原始缺陷已被修复。"""
    path = tmp_path / "multi.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(list(ROWS), columns=list(HEADER)).to_excel(
            writer, index=False, sheet_name="First"
        )
        pd.DataFrame(
            {"id": ["901"], "artist": ["second-sheet"], "count": ["1"], "note": ["x"]}
        ).to_excel(writer, index=False, sheet_name="Second")
    return path


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    path = tmp_path / "out"
    path.mkdir()
    return path


@pytest.fixture(autouse=True)
def _isolate_user_state(tmp_path_factory, monkeypatch):
    """避免测试写入开发者真实的配置/日志目录。"""
    from universal_table_splitter import settings as settings_module

    fake_dir = tmp_path_factory.mktemp("user-state")

    def fake_settings_path() -> Path:
        return fake_dir / "settings.json"

    monkeypatch.setattr(settings_module, "settings_path", fake_settings_path)
    monkeypatch.setattr(settings_module, "config_dir", lambda: fake_dir)
    monkeypatch.setattr(settings_module, "log_dir", lambda: fake_dir / "logs")
    yield
