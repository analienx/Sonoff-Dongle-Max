"""Defence-in-depth owner-epoch binding around the P009 snapshot stack.

p009_version performs a second secret-safe retained bridge/info read to enrich the
main snapshot with structured coordinator version metadata. This wrapper proves
that the exact Docker container id/start epoch is identical before, inside and
after that complete snapshot operation, preventing mixed-owner evidence if Z2M
restarts during the small enrichment window.
"""
from __future__ import annotations

import p009_common


def owner_key(owner: dict[str, object]) -> tuple[object, object, object]:
    return owner.get("container"), owner.get("container_id"), owner.get("started_at")


def validate_owner_consistency(
    snap: dict[str, object], before: dict[str, object], after: dict[str, object]
) -> dict[str, object]:
    evidence = snap.get("identity_evidence")
    embedded = evidence.get("owner") if isinstance(evidence, dict) else None
    if not isinstance(embedded, dict):
        raise RuntimeError("snapshot lacks embedded exact-owner evidence")
    keys = {owner_key(before), owner_key(embedded), owner_key(after)}
    if len(keys) != 1:
        raise RuntimeError(
            "Zigbee2MQTT owner/start epoch changed while collecting one snapshot: "
            f"before={owner_key(before)!r} embedded={owner_key(embedded)!r} after={owner_key(after)!r}"
        )
    proof = {
        "container": before.get("container"),
        "container_id": before.get("container_id"),
        "started_at": before.get("started_at"),
        "same_before_embedded_after": True,
    }
    if isinstance(evidence, dict):
        evidence["owner_consistency"] = proof
    return proof


def install() -> None:
    import p009_deploy

    original_snapshot = p009_deploy.snapshot

    def snapshot_owner_bound(host: str, addon: str, z2m_dir: str) -> dict[str, object]:
        before_container = p009_common.require_single_z2m_owner(host, addon)
        before = p009_common.container_session(host, before_container)
        snap = original_snapshot(host, addon, z2m_dir)
        after_container = p009_common.require_single_z2m_owner(host, addon)
        after = p009_common.container_session(host, after_container)
        validate_owner_consistency(snap, before, after)
        return snap

    p009_deploy.snapshot = snapshot_owner_bound
