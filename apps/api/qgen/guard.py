"""Gemini に渡す生徒由来の文と、Gemini の返答を Model Armor で検査する。

検査するもの：プロンプトインジェクションとジェイルブレイク、有害な表現（RAI）、悪意のあるURL、機密データ（SDP）。
検査できなかったとき（API の失敗、一部のフィルタの失敗）は「通さない」に倒す（fail closed）。
通さなかったときは Gemini を使わずテンプレートに戻すので、授業は止まらない。
"""
import logging
import os
import re
from typing import Protocol

logger = logging.getLogger(__name__)
TEMPLATE_PATTERN = r"^projects/[^/]+/locations/([a-z0-9-]+)/templates/[^/]+$"
TIMEOUT_SEC = 10


class Guard(Protocol):
    def screen_prompt(self, text: str) -> bool:
        """生徒由来の文を Gemini に渡してよければ True。"""

    def screen_response(self, text: str) -> bool:
        """Gemini の返答を人に見せてよければ True。"""


class NoGuard:
    """手元の開発とテスト用。何も検査しない。"""

    def screen_prompt(self, text: str) -> bool:
        return True

    def screen_response(self, text: str) -> bool:
        return True


def _name(value: object) -> str:
    """proto の列挙値でも文字列でも、名前で比べられるようにする。"""
    return getattr(value, "name", None) or str(value)


def _matched_filters(result) -> list[str]:
    """どのフィルタに引っかかったかを記録用に取り出す。取り出せなくても検査の結果は変わらない。"""
    matched = []
    try:
        for name, item in result.filter_results.items():
            data = type(item).to_dict(item, use_integers_for_enums=False)
            if "MATCH_FOUND" in str(data).replace("NO_MATCH_FOUND", ""):
                matched.append(name)
    except Exception:
        pass
    return matched


class ModelArmorGuard:
    def __init__(self, template: str, multi_language: bool = True, client=None) -> None:
        match = re.fullmatch(TEMPLATE_PATTERN, template)
        if not match:
            raise ValueError("MODEL_ARMOR_TEMPLATE は projects/{p}/locations/{l}/templates/{t} の形で指定してください")
        self._template = template
        self._multi_language = multi_language
        if client is None:
            from google.api_core.client_options import ClientOptions
            from google.cloud import modelarmor_v1

            # 検査は地域のエンドポイントでしか受け付けない
            endpoint = f"modelarmor.{match.group(1)}.rep.googleapis.com"
            client = modelarmor_v1.ModelArmorClient(transport="rest", client_options=ClientOptions(api_endpoint=endpoint))
        self._client = client

    def _metadata(self):
        if not self._multi_language:
            return None
        from google.cloud import modelarmor_v1

        # 日本語の文は、多言語の検出を有効にしないと検査されないことがある
        return modelarmor_v1.MultiLanguageDetectionMetadata(enable_multi_language_detection=True)

    def _passed(self, response, kind: str) -> bool:
        result = response.sanitization_result
        if _name(result.invocation_result) != "SUCCESS":
            logger.warning("Model Armor の検査が完了しなかったので通しません kind=%s result=%s", kind, _name(result.invocation_result))
            return False
        if _name(result.filter_match_state) != "NO_MATCH_FOUND":
            logger.warning("Model Armor が検出したので通しません kind=%s filters=%s", kind, ",".join(_matched_filters(result)) or "unknown")
            return False
        return True

    def screen_prompt(self, text: str) -> bool:
        try:
            from google.cloud import modelarmor_v1

            request = modelarmor_v1.SanitizeUserPromptRequest(
                name=self._template,
                user_prompt_data=modelarmor_v1.DataItem(text=text),
                multi_language_detection_metadata=self._metadata(),
            )
            return self._passed(self._client.sanitize_user_prompt(request=request, timeout=TIMEOUT_SEC), "prompt")
        except Exception:
            logger.exception("Model Armor でプロンプトを検査できなかったので通しません")
            return False

    def screen_response(self, text: str) -> bool:
        try:
            from google.cloud import modelarmor_v1

            request = modelarmor_v1.SanitizeModelResponseRequest(
                name=self._template,
                model_response_data=modelarmor_v1.DataItem(text=text),
                multi_language_detection_metadata=self._metadata(),
            )
            return self._passed(self._client.sanitize_model_response(request=request, timeout=TIMEOUT_SEC), "response")
        except Exception:
            logger.exception("Model Armor で返答を検査できなかったので通しません")
            return False


def default_guard() -> Guard | None:
    """MODEL_ARMOR_TEMPLATE があれば Model Armor を使う。なければ None を返し、呼び出し側が扱いを決める。"""
    template = os.environ.get("MODEL_ARMOR_TEMPLATE", "").strip()
    if not template:
        return None
    return ModelArmorGuard(template, multi_language=os.environ.get("MODEL_ARMOR_MULTI_LANGUAGE", "1") != "0")
