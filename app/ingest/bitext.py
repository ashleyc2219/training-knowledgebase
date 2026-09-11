"""Bitext Customer Support 資料集 → demo 種子與腳本票單。

資料集：bitext/Bitext-customer-support-llm-chatbot-training-dataset
（欄位 instruction / category / intent / response；CDLA-Sharing-1.0）。
策略見 docs/design/showme.md §11：每 intent 2 張歷史 resolved 當種子（不到 CREATE 門檻），
現場再餵第 3 張 → 轉真人 → CREATE v1 → 第 4 張 deflect → 第 5 張看再開票訊號。

執行：`python -m app.ingest.bitext`（下載失敗會用內建 fallback 列，並印出警告）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ID = "bitext/Bitext-customer-support-llm-chatbot-training-dataset"

INTENTS = ["cancel_order", "track_refund", "change_shipping_address"]

INTENT_FEATURE = {
    "cancel_order": "Cancel Order",
    "track_refund": "Track Refund",
    "change_shipping_address": "Change Shipping Address",
}

CUSTOMERS = ["alice@example.com", "bob@example.com"]

RAW_DIR = Path("data/raw")
SEED_PATH = Path("data/seed/bitext_seed.json")
SCRIPT_PATH = Path("data/script/demo_tickets.json")

SEED_PER_INTENT = 2
SCRIPT_PER_INTENT = 3

BASE_TIME = datetime(2026, 9, 1, 9, 0, 0, tzinfo=timezone.utc)

# 下載失敗時用的 Bitext 風格手寫列（instruction / category / intent / response）。
FALLBACK_ROWS: list[dict] = [
    # cancel_order（2 種子 + 3 腳本）
    {"intent": "cancel_order", "category": "ORDER", "instruction": "I want to cancel order {{Order Number}}", "response": "I'll help you cancel order {{Order Number}}. Go to {{Online Order Interaction}}, open the order and confirm the cancellation."},
    {"intent": "cancel_order", "category": "ORDER", "instruction": "how can I cancel my order {{Order Number}}?", "response": "Open {{Online Order Interaction}}, locate order {{Order Number}} and choose the cancel option before it ships."},
    {"intent": "cancel_order", "category": "ORDER", "instruction": "please cancel order {{Order Number}} for me", "response": "Sign in to {{Online Company Portal Info}}, open order {{Order Number}} and confirm the cancellation."},
    {"intent": "cancel_order", "category": "ORDER", "instruction": "I need help canceling the order {{Order Number}} I placed yesterday", "response": "You can cancel it yourself from {{Online Order Interaction}} while the order is still unshipped."},
    {"intent": "cancel_order", "category": "ORDER", "instruction": "cancelling order {{Order Number}} is not working for me", "response": "Please retry from {{Online Order Interaction}}; if the order already shipped you must start a return instead."},
    # track_refund（2 種子 + 3 腳本）
    {"intent": "track_refund", "category": "REFUND", "instruction": "where is my refund for order {{Order Number}}?", "response": "Check the refund status under {{Online Company Portal Info}}; refunds post within {{Money Amount}} business days."},
    {"intent": "track_refund", "category": "REFUND", "instruction": "I want to check the status of my refund", "response": "Open {{Online Company Portal Info}} and select the refund entry to see its current status."},
    {"intent": "track_refund", "category": "REFUND", "instruction": "how do I track the refund I requested last week?", "response": "Sign in and open the refunds section of {{Online Company Portal Info}} to follow the refund timeline."},
    {"intent": "track_refund", "category": "REFUND", "instruction": "need to see if my refund was processed", "response": "The refund status is shown in {{Online Company Portal Info}} next to the original order."},
    {"intent": "track_refund", "category": "REFUND", "instruction": "can you tell me about the status of my refund?", "response": "Look up the order in {{Online Company Portal Info}}; the refund status appears beside it."},
    # change_shipping_address（2 種子 + 3 腳本）
    {"intent": "change_shipping_address", "category": "SHIPPING", "instruction": "I need to change my shipping address", "response": "Go to {{Online Company Portal Info}}, open Addresses and edit the shipping address before the order ships."},
    {"intent": "change_shipping_address", "category": "SHIPPING", "instruction": "how can I update the delivery address of order {{Order Number}}?", "response": "Open order {{Order Number}} in {{Online Order Interaction}} and edit the delivery address."},
    {"intent": "change_shipping_address", "category": "SHIPPING", "instruction": "want to correct the shipping address I entered", "response": "Edit the address under {{Online Company Portal Info}} → Addresses, then reconfirm the order."},
    {"intent": "change_shipping_address", "category": "SHIPPING", "instruction": "please change where my order {{Order Number}} is being delivered", "response": "You can change it yourself in {{Online Order Interaction}} while the order is unshipped."},
    {"intent": "change_shipping_address", "category": "SHIPPING", "instruction": "my delivery address is wrong, how do I fix it?", "response": "Update it in {{Online Company Portal Info}} → Addresses and save before the order leaves the warehouse."},
]


def download() -> Path | None:
    """下載 Bitext 資料集檔到 data/raw/；失敗回 None。"""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    try:
        from huggingface_hub import hf_hub_download, list_repo_files

        files = list_repo_files(REPO_ID, repo_type="dataset")
        candidates = [f for f in files if f.endswith((".csv", ".parquet"))]
        if not candidates:
            return None
        filename = sorted(candidates, key=lambda f: (not f.endswith(".csv"), f))[0]
        path = hf_hub_download(
            repo_id=REPO_ID,
            repo_type="dataset",
            filename=filename,
            local_dir=str(RAW_DIR),
        )
        return Path(path)
    except Exception as exc:  # 黑客松：任何下載問題都退回 fallback
        print(f"[bitext] 下載失敗（{type(exc).__name__}: {exc}）")
        return None


def _load_rows() -> tuple[list[dict], bool]:
    """回傳 (rows, is_fallback)。rows 欄位：intent / category / instruction / response。"""
    path = download()
    if path is not None:
        try:
            import pandas as pd

            df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
            df.columns = [c.strip().lower() for c in df.columns]
            need = SEED_PER_INTENT + SCRIPT_PER_INTENT
            rows: list[dict] = []
            for intent in INTENTS:
                sub = df[df["intent"] == intent].head(need)
                if len(sub) < need:
                    raise ValueError(f"intent {intent} 列數不足（{len(sub)} < {need}）")
                for _, r in sub.iterrows():
                    rows.append(
                        {
                            "intent": intent,
                            "category": str(r["category"]),
                            "instruction": str(r["instruction"]),
                            "response": str(r["response"]),
                        }
                    )
            print(f"[bitext] 使用真實下載資料：{path}")
            return rows, False
        except Exception as exc:
            print(f"[bitext] 解析失敗（{type(exc).__name__}: {exc}）")

    print("[bitext] 警告：改用內建 fallback 手寫列（未使用真實 Bitext 下載資料）")
    return list(FALLBACK_ROWS), True


def _by_intent(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {intent: [] for intent in INTENTS}
    for row in rows:
        if row["intent"] in grouped:
            grouped[row["intent"]].append(row)
    return grouped


def _iso(index: int) -> str:
    return (BASE_TIME + timedelta(hours=index)).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_seed(rows: list[dict]) -> list[dict]:
    """每 intent 取 2 列 → data/seed/bitext_seed.json（歷史 resolved 票）。"""
    grouped = _by_intent(rows)
    seed: list[dict] = []
    for intent in INTENTS:
        for i, row in enumerate(grouped[intent][:SEED_PER_INTENT]):
            seed.append(
                {
                    "content": row["instruction"],
                    "resolution_steps": row["response"],
                    "category": row["category"],
                    "intent": intent,
                    "feature_name": INTENT_FEATURE[intent],
                    "customer_ref": CUSTOMERS[len(seed) % len(CUSTOMERS)],
                    "created_at": _iso(len(seed)),
                }
            )
    SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEED_PATH.write_text(json.dumps(seed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[bitext] 寫入 {SEED_PATH}（{len(seed)} 筆）")
    return seed


def build_script(rows: list[dict]) -> list[dict]:
    """每 intent 再取 3 列 → data/script/demo_tickets.json（現場餵的票）。

    cancel_order 第 3 張 alice、第 4 張 bob、第 5 張 alice（reopen_hint 標記再開票訊號）。
    """
    grouped = _by_intent(rows)
    script: list[dict] = []
    offset = SEED_PER_INTENT * len(INTENTS)
    cancel_customers = ["alice@example.com", "bob@example.com", "alice@example.com"]
    for intent in INTENTS:
        picks = grouped[intent][SEED_PER_INTENT : SEED_PER_INTENT + SCRIPT_PER_INTENT]
        for i, row in enumerate(picks):
            if intent == "cancel_order":
                customer = cancel_customers[i]
            else:
                customer = CUSTOMERS[(len(script)) % len(CUSTOMERS)]
            script.append(
                {
                    "content": row["instruction"],
                    "category": row["category"],
                    "intent": intent,
                    "feature_name": INTENT_FEATURE[intent],
                    "customer_ref": customer,
                    "created_at": _iso(offset + len(script)),
                    "reopen_hint": False,
                }
            )
    SCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCRIPT_PATH.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[bitext] 寫入 {SCRIPT_PATH}（{len(script)} 筆）")
    return script


def main() -> None:
    rows, is_fallback = _load_rows()
    build_seed(rows)
    build_script(rows)
    print(f"[bitext] 完成（來源：{'fallback 手寫列' if is_fallback else '真實下載'}）")


if __name__ == "__main__":
    main()
