"""
Task 3: Multi-Intent Query Parser
==================================
Uses OpenAI Chat Completions with a few-shot system prompt to decompose a
user's natural-language question (Vietnamese or mixed) into a structured
JSON object containing one or more intents.

Intent schema
-------------
{
  "intents": [
    {
      "type": "scan_errors" | "node_info" | "general",
      "target": "<device_name | error_subtype | null>",
      "clean_query": "<minimal clean Vietnamese query>"
    }
  ]
}

Intent types
------------
- scan_errors : trigger Cypher-based audit queries
    targets: "SPOF", "loop", "vlan_mismatch", "topology_violation", "all"
- node_info   : trigger k-hop neighborhood traversal for a specific device
    target: exact device name (e.g. "SW-CORE-FT-01")
- general     : fallback → vector similarity search
    target: null
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional

from config.settings import llm_config

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ParsedIntent:
    type: str                       # "scan_errors" | "node_info" | "general"
    target: Optional[str]           # device name / error subtype / None
    clean_query: str                # minimal clean query string


@dataclass
class ParsedQuery:
    intents: List[ParsedIntent] = field(default_factory=list)
    raw_response: str = ""


# ---------------------------------------------------------------------------
# System prompt (few-shot)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
Bạn là một trợ lý phân tích mạng lưới viễn thông. Nhiệm vụ của bạn là phân tích câu hỏi của người dùng \
và trích xuất ra các "ý định" (intent) rõ ràng.

## QUY TẮC BẮT BUỘC:
1. Chỉ trả về JSON thuần túy, KHÔNG có markdown, KHÔNG có giải thích, KHÔNG có ```json``` block.
2. Output phải là object JSON hợp lệ theo schema sau:
   {"intents": [{"type": "...", "target": "...", "clean_query": "..."}]}
3. Trường "type" chỉ được nhận một trong ba giá trị: "scan_errors", "node_info", "general"
4. Trường "target" với type="scan_errors" chỉ nhận: "SPOF", "loop", "vlan_mismatch", "topology_violation", "all"
5. Trường "target" với type="node_info" phải là tên thiết bị chính xác được đề cập trong câu hỏi.
6. Trường "target" với type="general" luôn là null.
7. Trường "clean_query" chỉ giữ lại thông tin cốt lõi, loại bỏ câu chào hỏi, văn phong thừa.
8. Nếu câu hỏi có nhiều ý định, liệt kê tất cả trong mảng "intents".
9. TUYỆT ĐỐI không thêm bất kỳ nội dung nào ngoài JSON.

## VÍ DỤ CÂU HỎI ĐƠN Ý ĐỊNH (single-intent):

Câu hỏi: "Mạng hiện tại có thiết bị nào đang là SPOF không?"
Output:
{"intents":[{"type":"scan_errors","target":"SPOF","clean_query":"thiết bị SPOF trong mạng"}]}

Câu hỏi: "Cho tôi biết thông tin của SW-CORE-FT-01"
Output:
{"intents":[{"type":"node_info","target":"SW-CORE-FT-01","clean_query":"thông tin thiết bị SW-CORE-FT-01"}]}

Câu hỏi: "Có lỗi VLAN mismatch ở đâu không?"
Output:
{"intents":[{"type":"scan_errors","target":"vlan_mismatch","clean_query":"lỗi VLAN mismatch"}]}

Câu hỏi: "Liệt kê tất cả các thiết bị đang gặp lỗi"
Output:
{"intents":[{"type":"scan_errors","target":"all","clean_query":"tất cả thiết bị đang có lỗi"}]}

## VÍ DỤ CÂU HỎI ĐA Ý ĐỊNH (multi-intent):

Câu hỏi: "SW-AGG-POD0-NODE1 có phải là SPOF không, và trong mạng có vòng lặp nào không?"
Output:
{"intents":[{"type":"node_info","target":"SW-AGG-POD0-NODE1","clean_query":"thông tin và trạng thái SPOF của SW-AGG-POD0-NODE1"},{"type":"scan_errors","target":"loop","clean_query":"vòng lặp mạng L2"}]}

Câu hỏi: "Kiểm tra SW-EDGE-POD1-NODE2 và xem có lỗi VLAN mismatch hay vi phạm cấu trúc topology nào không?"
Output:
{"intents":[{"type":"node_info","target":"SW-EDGE-POD1-NODE2","clean_query":"thông tin SW-EDGE-POD1-NODE2"},{"type":"scan_errors","target":"vlan_mismatch","clean_query":"lỗi VLAN mismatch"},{"type":"scan_errors","target":"topology_violation","clean_query":"vi phạm cấu trúc topology"}]}
"""


# ---------------------------------------------------------------------------
# Parser class
# ---------------------------------------------------------------------------


class MultiIntentQueryParser:
    """
    Sends the user query to OpenAI with a few-shot system prompt and
    parses the returned JSON into ParsedQuery / ParsedIntent dataclasses.
    """

    def __init__(self) -> None:
        if not llm_config.OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY is not set. Please add it to your .env file."
            )
        from openai import OpenAI  # type: ignore
        self._client = OpenAI(api_key=llm_config.OPENAI_API_KEY)
        self._model = llm_config.OPENAI_MODEL

    def parse(self, user_query: str) -> ParsedQuery:
        """
        Parse the user query into structured intents.

        Args:
            user_query: Raw user input string.

        Returns:
            ParsedQuery with a list of ParsedIntent objects.
        """
        safe_query = user_query.strip()

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                temperature=0.0,         # deterministic parsing
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": f'Câu hỏi: "{safe_query}"\nOutput:'},
                ],
            )
            raw_text = response.choices[0].message.content.strip()
        except Exception as exc:
            print(f"[QueryParser] LLM call failed: {exc}")
            return self._fallback_general(user_query)

        try:
            data = self._extract_json(raw_text)
            intents = []
            for item in data.get("intents", []):
                intents.append(
                    ParsedIntent(
                        type=item.get("type", "general"),
                        target=item.get("target") or None,
                        clean_query=item.get("clean_query", safe_query),
                    )
                )
            if not intents:
                return self._fallback_general(user_query)
            return ParsedQuery(intents=intents, raw_response=raw_text)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            print(f"[QueryParser] Failed to parse LLM JSON output: {exc}\nRaw: {raw_text}")
            return self._fallback_general(user_query)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json(text: str) -> dict:
        """
        Extract the first valid JSON object from the LLM response.
        Handles cases where the model wraps output in markdown code fences.
        """
        cleaned = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise json.JSONDecodeError("No valid JSON found", text, 0)

    @staticmethod
    def _fallback_general(user_query: str) -> ParsedQuery:
        """Return a single general intent as fallback when parsing fails."""
        return ParsedQuery(
            intents=[
                ParsedIntent(
                    type="general",
                    target=None,
                    clean_query=user_query.strip(),
                )
            ],
            raw_response="[fallback]",
        )
