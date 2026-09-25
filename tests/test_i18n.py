"""国际化一致性测试。

原实现里同一个校验函数一半走 i18n、一半硬编码英文（"Chunk size must be positive"），
外加 README 宣称"完整错误信息本地化"。这组测试用静态扫描把这类回归挡住。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from universal_table_splitter import i18n
from universal_table_splitter.errors import (
    AppError,
    CanceledByUser,
    DependencyError,
    FileFormatError,
    OutputError,
    ValidationError,
)

PACKAGE_DIR = Path(i18n.__file__).parent
KEY_PREFIXES = (
    "app.",
    "btn.",
    "label.",
    "hint.",
    "status.",
    "summary.",
    "confirm.",
    "info.",
    "err.",
    "about.",
    "cli.",
    "dep.",
)
_PREFIX_ALTERNATION = "|".join(prefix.replace(".", r"\.") for prefix in KEY_PREFIXES)
KEY_PATTERN = re.compile(r'"((?:' + _PREFIX_ALTERNATION + r')[a-z0-9_.]+)"')


#: 与 i18n key 前缀同形、但并非文案的字面量
NON_TEXT_LITERALS = {"app.log"}


def _source_files() -> list[Path]:
    return sorted(PACKAGE_DIR.rglob("*.py"))


def test_both_languages_define_the_same_keys():
    chinese = set(i18n.LANGUAGES["cn"])
    english = set(i18n.LANGUAGES["en"])
    assert chinese == english
    assert len(chinese) > 50


@pytest.mark.parametrize("lang", ["cn", "en"])
def test_every_template_is_formattable(lang):
    for key, template in i18n.LANGUAGES[lang].items():
        fields = set(re.findall(r"\{(\w+)\}", template))
        rendered = template.format(**{name: "x" for name in fields})
        assert "{" not in rendered and "}" not in rendered, key


def test_no_duplicate_placeholder_mismatch():
    """两个语言的同一 key 必须声明同一组占位符，否则切换语言会丢字段。"""
    for key in i18n.LANGUAGES["cn"]:
        cn_fields = set(re.findall(r"\{(\w+)\}", i18n.LANGUAGES["cn"][key]))
        en_fields = set(re.findall(r"\{(\w+)\}", i18n.LANGUAGES["en"][key]))
        assert cn_fields == en_fields, key


def test_all_keys_referenced_in_code_exist():
    unknown: list[str] = []
    for path in _source_files():
        for key in KEY_PATTERN.findall(path.read_text(encoding="utf-8")):
            if key in NON_TEXT_LITERALS:
                continue
            if key not in i18n.LANGUAGES["cn"]:
                unknown.append(f"{path.name}: {key}")
            elif key not in i18n.LANGUAGES["en"]:
                unknown.append(f"{path.name}: {key} (missing in en)")
    assert unknown == []


def test_languages_table_is_only_indexed_inside_i18n():
    """其它模块只能通过 ``tr()`` 取文案，禁止直接索引 ``LANGUAGES[...]``。

    原实现正是到处直接索引嵌套字典，才导致状态栏出现 ``Error: ...`` 这类硬编码前缀。
    """
    offenders = []
    for path in _source_files():
        if path.name == "i18n.py":
            continue
        if re.search(r"LANGUAGES\s*\[", path.read_text(encoding="utf-8")):
            offenders.append(path.name)
    assert offenders == []


@pytest.mark.parametrize(
    "error_class", [AppError, ValidationError, FileFormatError, DependencyError, OutputError]
)
def test_error_default_keys_are_translated(error_class):
    assert error_class.default_key in i18n.LANGUAGES["cn"]
    assert error_class.default_key in i18n.LANGUAGES["en"]


def test_canceled_by_user_is_not_a_localised_error():
    """取消是控制流信号，不应被当成需要渲染的错误文案。"""
    assert not issubclass(CanceledByUser, AppError)


def test_tr_renders_context():
    assert "S2" in i18n.tr("err.sheet_not_found", "cn", sheet="S2")
    assert "S2" in i18n.tr("err.sheet_not_found", "en", sheet="S2")


def test_tr_ignores_missing_context_instead_of_raising():
    assert i18n.tr("status.running") == i18n.LANGUAGES["cn"]["status.running"]


def test_tr_falls_back_to_chinese_then_key():
    assert i18n.tr("btn.start", "en") == "Start Splitting"
    assert i18n.tr("btn.start", "de") == "开始分割"
    assert i18n.tr("does.not.exist") == "does.not.exist"


def test_render_error_localises_app_error():
    message = i18n.render_error(AppError("err.sheet_not_found", sheet="Sheet3"), "en")
    assert "Sheet3" in message and "Worksheet" in message


def test_render_error_passes_through_plain_exceptions():
    assert i18n.render_error(ValueError("boom"), "cn") == "boom"


def test_languages_registry_matches_languages_table():
    assert set(i18n.SUPPORTED_LANGS) == set(i18n.LANGUAGES)
