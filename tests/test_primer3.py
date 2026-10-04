"""primer3-pyラッパー（A-09）のテスト。

primer3-pyが未インストールの環境でも、`design_primers`は素の`ImportError`を
そのまま漏らさず、明確なメッセージを持つ`Primer3Error`（SeqAtelierError系列）を
送出することを検証する。

この開発環境には`primer3-py`が実際にインストールされているため、
`sys.modules["primer3"] = None`を仕込んで`import primer3`が`ImportError`を
送出する状態を再現する（Pythonの`import`機構は`sys.modules[name]`が`None`の
場合に`ImportError`を送出する）。
"""

from __future__ import annotations

import sys

import pytest

from seqatelier.primer.primer3 import Primer3Error, design_primers


def test_primer3_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "primer3", None)

    with pytest.raises(Primer3Error) as excinfo:
        design_primers("ACGT" * 20, target_region=(10, 20))

    message = str(excinfo.value)
    # 素のImportErrorではなく、SeqAtelier独自の明確なエラーメッセージであること
    assert "primer3-py" in message
    assert "pip install" in message


def test_primer3_installed_basic_design():
    """primer3-pyが実際にインストールされている環境では、汎用プライマー設計が動作すること（A-09正常系）。"""
    pytest.importorskip("primer3")

    template = ("ACGT" * 20) + "ATGGCTAGCATGGCTAGCATGGCTAGCATGGCTAGCATGGCTAGC" + ("ACGT" * 20)
    result = design_primers(template, target_region=(80, 20))

    assert isinstance(result, dict)
    assert "PRIMER_LEFT_NUM_RETURNED" in result
