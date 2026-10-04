"""primer3-pyラッパーのスタブ（WC-5）。

`pip install seqatelier[primer3]`でオプション依存として`primer3-py`が入っている
場合のみ動作する。In-Fusion/QuikChange以外の汎用PCRプライマー設計を担う想定。
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from seqatelier.core.types import SeqAtelierError

__all__ = ["Primer3Error", "design_primers"]


class Primer3Error(SeqAtelierError):
    """`primer3-py`が利用できない、または設計に失敗した場合に送出される。"""


def design_primers(
    template: str,
    target_region: tuple[int, int],
    **primer3_args: Any,
) -> dict[str, Any]:
    """`primer3-py`を使って汎用プライマーを設計する（WC-5）。

    Parameters
    ----------
    template:
        鋳型配列（塩基配列文字列）。
    target_region:
        `(start, length)` — primer3の`SEQUENCE_TARGET`形式（0-based、
        配列上の増幅対象領域）。
    **primer3_args:
        `primer3-py`の`bindings.design_primers()`にそのまま渡す追加パラメータ
        （例: `PRIMER_OPT_SIZE`, `PRIMER_PRODUCT_SIZE_RANGE`等）。

    Returns
    -------
    dict
        `primer3-py`の生の戻り値をそのまま返す（構造化dict、JSONシリアライズ可能）。

    Raises
    ------
    Primer3Error
        `primer3-py`がインストールされていない場合
        （`pip install seqatelier[primer3]`を促す）、または設計に失敗した場合。
    """
    try:
        primer3 = import_module("primer3")
    except ImportError as exc:
        raise Primer3Error(
            "primer3-pyがインストールされていません。'pip install seqatelier[primer3]'"
            "（または'pip install primer3-py'）を実行してください。"
        ) from exc

    seq_args = {
        "SEQUENCE_TEMPLATE": template,
        "SEQUENCE_TARGET": list(target_region),
    }
    global_args = {
        "PRIMER_OPT_SIZE": 20,
        "PRIMER_PICK_INTERNAL_OLIGO": 0,
        "PRIMER_MIN_SIZE": 18,
        "PRIMER_MAX_SIZE": 27,
        **primer3_args,
    }
    try:
        result = primer3.bindings.design_primers(seq_args, global_args)  # type: ignore[attr-defined]
    except Exception as exc:  # primer3-pyはさまざまな例外を送出しうる
        raise Primer3Error(f"primer3による設計に失敗しました: {exc}") from exc
    return dict(result)
