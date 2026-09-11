"""HydraDB（Memory 儲存層）：跨 session 知識圖譜與多跳查詢。

**接法（2026-09-11 拿到 HydraDB Cloud 憑證後定案）：**

1. HydraDB Cloud v2 的 REST 沒有 Cypher 端點（是 `/databases`、`/context/ingest`、
   `/context/relations`、`/query` 這組「context delivery」API；官方文件
   https://docs.hydradb.com/api-reference/v2 ）。所以本 client 採 **write-through**：
   - 本機 `.state/graph.json` 永遠寫，當作決定性的索引，五種邊的多跳查詢在這裡算；
   - `HYDRADB_URI` 有值時，每個節點／邊同步 ingest 成 HydraDB **memory**
     （`POST /context/ingest`, type=memory, database=`HYDRADB_DATABASE`,
     collection=`HYDRADB_COLLECTION`），HydraDB 自己抽實體與關係、跨 session 保存；
   - `recall()` 走 `POST /query`（graph_context=true）、`relations()` 走
     `GET /context/relations`，給 UI 展示「HydraDB 記住了什麼」。
   HydraDB 那邊失敗只記 `last_error`、不 raise（showme §17：記憶層降級不擋資料層）。
2. `cypher()` **不是** Cypher parser，只吃幾個具名模板（`CYPHER_TEMPLATES`）。
   本專案只需要固定那幾種查詢，寫 parser 是過度設計。

邊只有五種（`docs/design/showme.md` §10）：
asks_about / explains / refers_to / changes / supersedes；白名單外一律 `OperationFailed`。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.config import Settings
from app.errors import OperationFailed

DEFAULT_PATH = ".state/graph.json"

ALLOWED_RELS = {"asks_about", "explains", "refers_to", "changes", "supersedes"}

ALLOWED_LABELS = {
    "Ticket",
    "UserProblem",
    "Feature",
    "Tutorial",
    "TutorialVersion",
    "Feedback",
    "Release",
    "Workflow",
}

# cypher() 接受的具名模板（見模組 docstring 的簡化說明）。
CYPHER_TEMPLATES = (
    "ping",
    "affected_by_release",
    "tickets_by_feature",
    "published_tutorial_for_problem",
)


def _key_id(label: str, key: dict) -> str:
    """節點身分字串：label ＋ 排序後的 key 欄位。"""
    return label + "|" + json.dumps(key, sort_keys=True, ensure_ascii=False)


class HydraDBClient:
    """圖譜 client。本機 JSON 永遠寫；`HYDRADB_URI` 有值時同步鏡射到 HydraDB Cloud。"""

    def __init__(
        self,
        path: str = DEFAULT_PATH,
        settings: Optional[Settings] = None,
        transport: Any = None,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.uri = (self.settings.HYDRADB_URI or "").rstrip("/") or None
        self.database = self.settings.HYDRADB_DATABASE or "support_tutorials"
        self.collection = self.settings.HYDRADB_COLLECTION or "graph"
        self.last_error: Optional[str] = None
        self.mirrored = 0  # 成功 ingest 到 HydraDB 的筆數（demo 展示用）
        self._transport = transport  # 測試注入 httpx.MockTransport
        self._http = None

    # --- transport（HydraDB Cloud v2 REST） ---

    def _client(self):
        import httpx  # 延遲匯入：本機 backend 與單元測試不需要

        if self._http is None:
            self._http = httpx.Client(
                base_url=self.uri or "",
                headers={
                    "Authorization": f"Bearer {self.settings.HYDRADB_APIKEY or ''}",
                    "API-Version": "2",
                },
                timeout=15,
                transport=self._transport,
            )
        return self._http

    @staticmethod
    def _describe(label: str, key: dict, props: Optional[dict] = None) -> str:
        parts = [f"{k}={v}" for k, v in (key or {}).items()]
        parts += [f"{k}={v}" for k, v in (props or {}).items() if v not in (None, "")]
        return f"{label} (" + ", ".join(parts) + ")"

    def _post(self, payload: dict) -> bool:
        """把一個節點／邊 ingest 成 HydraDB memory；失敗回 False 並記 last_error，永不 raise。"""
        if not self.uri:
            return False
        if payload["op"] == "upsert_node":
            text = self._describe(payload["label"], payload["key"], payload.get("props")) + "."
            meta = {"kind": "node", "label": payload["label"], "key": json.dumps(payload["key"], ensure_ascii=False)}
        else:
            fl, fk = payload["from"]
            tl, tk = payload["to"]
            text = f"{self._describe(fl, fk)} {payload['rel']} {self._describe(tl, tk)}."
            meta = {"kind": "edge", "rel": payload["rel"], "from": fl, "to": tl}
        try:
            resp = self._client().post(
                "/context/ingest",
                data={
                    "type": "memory",
                    "database": self.database,
                    "collection": self.collection,
                    "upsert": "true",
                    "memories": json.dumps([{"text": text, "metadata": meta}], ensure_ascii=False),
                },
            )
            if resp.status_code >= 300:
                self.last_error = f"HydraDB ingest {resp.status_code}: {resp.text[:200]}"
                return False
            self.mirrored += 1
            return True
        except Exception as exc:  # noqa: BLE001 - 記憶層降級
            self.last_error = f"HydraDB ingest failed: {exc}"
            return False

    def recall(self, query: str, top_k: int = 5) -> dict:
        """POST /query（memory, graph_context）：回 {chunks, graph, error}。"""
        if not self.uri:
            return {"chunks": [], "graph": {}, "error": "HYDRADB_URI 未設定（本機 backend）"}
        try:
            resp = self._client().post(
                "/query",
                json={
                    "database": self.database,
                    "collection": self.collection,
                    "type": "memory",
                    "query": query,
                    "max_results": top_k,
                    "graph_context": True,
                },
            )
            if resp.status_code >= 300:
                return {"chunks": [], "graph": {}, "error": f"{resp.status_code}: {resp.text[:200]}"}
            data = resp.json().get("data") or {}
            return {"chunks": data.get("chunks") or [], "graph": data.get("graph") or {}, "error": None}
        except Exception as exc:  # noqa: BLE001
            return {"chunks": [], "graph": {}, "error": str(exc)}

    def relations(self, limit: int = 50) -> list[dict]:
        """GET /context/relations（memory）：HydraDB 自己抽出的 triplets。"""
        if not self.uri:
            return []
        try:
            resp = self._client().get(
                "/context/relations",
                params={"database": self.database, "collection": self.collection, "type": "memory", "limit": limit},
            )
            if resp.status_code >= 300:
                self.last_error = f"HydraDB relations {resp.status_code}"
                return []
            return (resp.json().get("data") or {}).get("relations") or []
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"HydraDB relations failed: {exc}"
            return []

    def remote_status(self) -> dict:
        """GET /databases/status ＋ /databases/stats（UI 展示用）。"""
        if not self.uri:
            return {"backend": "local", "path": str(self.path)}
        out: dict = {"backend": "hydradb", "database": self.database, "collection": self.collection}
        try:
            st = self._client().get("/databases/status", params={"database": self.database}).json().get("data") or {}
            out["ready_for_ingestion"] = (st.get("infra") or {}).get("ready_for_ingestion")
            stats = self._client().get("/databases/stats", params={"database": self.database}).json().get("data") or {}
            out["memory_rows"] = (stats.get("memory_collection") or {}).get("row_count")
        except Exception as exc:  # noqa: BLE001
            out["error"] = str(exc)
        return out

    # --- 本機 JSON backend ---

    def _load(self) -> dict:
        if not self.path.exists():
            return {"nodes": {}, "edges": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise OperationFailed(f"讀取圖譜檔失敗：{exc}") from exc
        data.setdefault("nodes", {})
        data.setdefault("edges", {})
        return data

    def _save(self, data: dict) -> None:
        try:
            self.path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            raise OperationFailed(f"寫入圖譜檔失敗：{exc}") from exc

    # --- 寫入 ---

    def _canon_key(self, label: str, key) -> dict:
        """統一各呼叫端的 key 寫法（hackathon 簡化，避免 seed／create／release 各用一套）：
        scalar → {"id": v}；Tutorial {"id"} → {"tutorial_id"}；Feature {"id"} → 對回既有節點的 {"name"}。"""
        if not isinstance(key, dict):
            key = {"id": key}
        if label == "Tutorial" and "tutorial_id" not in key and "id" in key:
            key = {"tutorial_id": key["id"]}
        if label == "Feature" and "name" not in key and "id" in key:
            for node in self.nodes("Feature"):
                if node["props"].get("id") == key["id"] or node["key"] == key:
                    return dict(node["key"])
        return key

    def upsert_node(self, label: str, key: dict, props: dict) -> None:
        """MERGE (n:<label> {<key>}) SET n += props。"""
        if label not in ALLOWED_LABELS:
            raise OperationFailed(f"不允許的節點 label：{label}")
        key = self._canon_key(label, key)
        data = self._load()
        nid = _key_id(label, key)
        node = data["nodes"].get(nid) or {"label": label, "key": key, "props": {}}
        node["props"].update(props or {})
        data["nodes"][nid] = node
        self._save(data)
        self._post({"op": "upsert_node", "label": label, "key": key, "props": node["props"]})

    def upsert_edge(
        self,
        from_label: str,
        from_key: dict,
        rel: str,
        to_label: str,
        to_key: dict,
    ) -> None:
        """MERGE (a)-[:<rel>]->(b)；rel 不在五種白名單內就 `操作失敗`。"""
        if rel not in ALLOWED_RELS:
            raise OperationFailed(f"不允許的邊型別：{rel}（只允許 {sorted(ALLOWED_RELS)}）")
        if from_label not in ALLOWED_LABELS or to_label not in ALLOWED_LABELS:
            raise OperationFailed(f"不允許的節點 label：{from_label} / {to_label}")
        from_key = self._canon_key(from_label, from_key)
        to_key = self._canon_key(to_label, to_key)
        data = self._load()
        src = _key_id(from_label, from_key)
        dst = _key_id(to_label, to_key)
        data["edges"][f"{src}|-{rel}->|{dst}"] = {
            "from_label": from_label,
            "from_key": from_key,
            "rel": rel,
            "to_label": to_label,
            "to_key": to_key,
        }
        self._save(data)
        self._post({"op": "upsert_edge", "from": [from_label, from_key], "rel": rel, "to": [to_label, to_key]})

    # --- 讀取 ---

    def nodes(self, label: Optional[str] = None) -> list[dict]:
        data = self._load()
        out = list(data["nodes"].values())
        return [n for n in out if label is None or n["label"] == label]

    def edges(self, rel: Optional[str] = None) -> list[dict]:
        data = self._load()
        out = list(data["edges"].values())
        return [e for e in out if rel is None or e["rel"] == rel]

    def affected_tutorials_by_release(self, release_id: int) -> list[dict]:
        """多跳：(Release)-[:changes]->(Feature)<-[:explains]-(Tutorial)。"""
        changed = {
            _key_id(e["to_label"], e["to_key"])
            for e in self.edges("changes")
            if e["from_label"] == "Release" and e["from_key"].get("id") == release_id
        }
        hits: list[dict] = []
        for e in self.edges("explains"):
            if e["from_label"] != "Tutorial":
                continue
            if _key_id(e["to_label"], e["to_key"]) not in changed:
                continue
            node = self._node(e["from_label"], e["from_key"])
            hit = dict(e["from_key"])
            hit.update(node["props"] if node else {})
            hits.append(hit)
        return hits

    def has_published_tutorial(self, user_problem_id: int) -> bool:
        """該 UserProblem 是否已有 status = published 的 Tutorial。"""
        for node in self.nodes("Tutorial"):
            props = node["props"]
            if (
                props.get("user_problem_id") == user_problem_id
                and props.get("status") == "published"
            ):
                return True
        return False

    def cypher(self, query: str, params: Optional[dict] = None) -> list[dict]:
        """具名模板查詢（不是 Cypher parser，見模組 docstring）。"""
        params = params or {}
        if query not in CYPHER_TEMPLATES:
            raise OperationFailed(
                f"未知的查詢模板：{query!r}；只支援 {list(CYPHER_TEMPLATES)}"
            )
        if query == "ping":
            self._load()
            return [{"ok": 1}]
        if query == "affected_by_release":
            return self.affected_tutorials_by_release(params["release_id"])
        if query == "tickets_by_feature":
            target = _key_id("Feature", {"name": params["name"]})
            count = sum(
                1
                for e in self.edges("asks_about")
                if e["from_label"] == "Ticket"
                and _key_id(e["to_label"], e["to_key"]) == target
            )
            return [{"c": count}]
        return [{"ok": self.has_published_tutorial(params["user_problem_id"])}]

    def _node(self, label: str, key: dict) -> Optional[dict]:
        return self._load()["nodes"].get(_key_id(label, self._canon_key(label, key)))


_default: Optional[HydraDBClient] = None


def get_client() -> HydraDBClient:
    """模組層預設 client（給煙測與 demo 用）。"""
    global _default
    if _default is None:
        _default = HydraDBClient()
    return _default


def upsert_node(label: str, key: dict, props: dict) -> None:
    get_client().upsert_node(label, key, props)


def upsert_edge(from_label: str, from_key: dict, rel: str, to_label: str, to_key: dict) -> None:
    get_client().upsert_edge(from_label, from_key, rel, to_label, to_key)


def cypher(query: str, params: Optional[dict] = None) -> list[dict]:
    return get_client().cypher(query, params)
