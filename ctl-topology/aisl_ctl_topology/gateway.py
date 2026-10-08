"""Public Knowledge API only. Every query pins revision, artifact and record kind."""
from __future__ import annotations

from urllib.parse import quote

CTL_RECORD_KINDS = (
    "ctl_flow", "ctl_entity", "ctl_flow_entity", "ctl_trigger",
    "ctl_schedule", "ctl_lock", "ctl_dependency", "ctl_dependency_gap",
)


class AislCtlGateway:
    def __init__(self, base_url: str, *, timeout_sec: float = 45) -> None:
        from aisl_sdk import AislClient
        self._client = AislClient(base_url, timeout_sec=timeout_sec)

    def close(self) -> None:
        self._client.close()

    def load_revision(self, system_id: str, revision_id: str) -> dict:
        revision = self._client.revision(system_id, revision_id)
        products = [p for p in revision.list_products(capability="common.ctl-orchestration")
                    if p.model_kind == "ctl-orchestration" and p.schema_version == "ctl-orchestration/v1"]
        if len(products) != 1:
            raise ValueError(f"{system_id}/{revision_id}: expected exactly one published CTL orchestration product, found {len(products)}")
        artifact_id = str(products[0].artifact_id)
        base = f"/api/knowledge/v1/systems/{quote(system_id, safe='')}/knowledge-artifacts/{quote(artifact_id, safe='')}/records"
        records = {}
        for kind in CTL_RECORD_KINDS:
            rows = []
            offset = 0
            while True:
                page = self._client.get_json(
                    f"{base}/{kind}", params={"revision_id": revision_id, "offset": offset, "limit": 500}
                )
                if page.get("system_id") != system_id or page.get("revision_id") != revision_id or page.get("artifact_id") != artifact_id or page.get("record_kind") != kind:
                    raise RuntimeError("public CTL page identity mismatch")
                items = page.get("items")
                meta = page.get("page")
                if not isinstance(items, list) or not isinstance(meta, dict):
                    raise RuntimeError("invalid public CTL page")
                if len(items) > 500 or not all(isinstance(row, dict) for row in items):
                    raise RuntimeError("invalid CTL row envelope")
                rows.extend(items)
                offset += len(items)
                total = meta.get("total")
                if not isinstance(total, int) or total < offset:
                    raise RuntimeError("invalid public CTL total")
                if offset == total:
                    break
                if not items:
                    raise RuntimeError("public CTL pagination stalled")
            records[kind] = rows
        return {"system_id": system_id, "revision_id": revision_id, "artifact_id": artifact_id, "records": records}
