"""container engineの実行コンテキストを正規化する。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Tuple


@dataclass(frozen=True)
class RuntimeContext:
    """同じcontainer storeを見ているか確認するための実行コンテキスト。"""

    engine: str
    uid: Optional[int]
    rootless: Optional[bool]
    version: Optional[str]
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine": self.engine,
            "uid": self.uid,
            "rootless": self.rootless,
            "version": self.version,
            "warnings": list(self.warnings),
        }


def normalize_runtime_context(
    engine: str,
    uid_stdout: str,
    info: Mapping[str, Any],
) -> RuntimeContext:
    """Docker/PodmanのinfoとSSHユーザーUIDからcontextを作る。"""
    uid: Optional[int]
    try:
        uid = int(uid_stdout.strip())
    except ValueError:
        uid = None

    host = info.get("host")
    host_map = host if isinstance(host, Mapping) else {}
    rootless_value = host_map.get("rootless")
    rootless: Optional[bool]
    if isinstance(rootless_value, bool):
        rootless = rootless_value
    else:
        security_options = info.get("SecurityOptions", [])
        if isinstance(security_options, list):
            rootless = any("rootless" in str(item).lower() for item in security_options)
        else:
            rootless = None

    version_value = info.get("Version") or info.get("ServerVersion") or info.get("version")
    version = str(version_value) if version_value else None
    warnings = []
    if rootless is None:
        warnings.append("runtimeのrootless/rootfulを判定できません。移送前に実行ユーザーを確認してください。")
    if uid is None:
        warnings.append("SSH接続ユーザーのUIDを判定できません。bind mountの所有権を確認してください。")

    return RuntimeContext(
        engine=engine,
        uid=uid,
        rootless=rootless,
        version=version,
        warnings=tuple(warnings),
    )


def compare_runtime_contexts(source: RuntimeContext, destination: RuntimeContext) -> Tuple[str, ...]:
    """移送元と移送先のcontext差分を警告へ変換する。"""
    warnings = list(source.warnings) + list(destination.warnings)
    if source.engine != destination.engine:
        warnings.append(f"engineが異なります: source={source.engine}, destination={destination.engine}")
    if source.rootless is not None and destination.rootless is not None:
        if source.rootless != destination.rootless:
            warnings.append("移送元と移送先でrootless/rootfulが異なります。自動切替は行いません。")
    if source.uid is not None and destination.uid is not None and source.uid != destination.uid:
        warnings.append(f"SSH接続ユーザーのUIDが異なります: source={source.uid}, destination={destination.uid}")
    return tuple(dict.fromkeys(warnings))
