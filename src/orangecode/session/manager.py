"""会话持久化与恢复管理器。"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from orangecode.config import settings


@dataclass
class SessionMetadata:
    """会话的元数据描述。"""

    conversation_id: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    message_count: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionRecord:
    """保存在磁盘上的完整会话镜像。"""

    metadata: SessionMetadata
    messages: list[dict[str, Any]] = field(default_factory=list)


class SessionManager:
    """管理会话磁盘存储与检索。"""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = (base_dir or settings.state_dir) / "sessions"
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _file_path(self, conversation_id: str) -> Path:
        # 简单安全的文件名映射
        safe_id = "".join(c for c in conversation_id if c.isalnum() or c in ("-", "_"))
        return self.base_dir / f"{safe_id}.json"

    def save(
        self,
        conversation_id: str,
        messages: list[dict[str, Any]],
        extra: dict[str, Any] | None = None,
    ) -> SessionRecord:
        """原子持久化保存会话历史。"""
        path = self._file_path(conversation_id)
        now_str = datetime.now().isoformat()

        # 如果已有历史，保留其 created_at
        created_at = now_str
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                created_at = existing.get("metadata", {}).get("created_at", now_str)
            except Exception:
                pass

        meta = SessionMetadata(
            conversation_id=conversation_id,
            created_at=created_at,
            updated_at=now_str,
            message_count=len(messages),
            extra=extra or {},
        )
        record = SessionRecord(metadata=meta, messages=messages)

        # 原子写入：先写入临时文件，再原子重命名替换
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(asdict(record), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(path)
        logger.debug(f"Saved session {conversation_id} ({len(messages)} messages) to {path}")
        return record

    def load(self, conversation_id: str) -> SessionRecord | None:
        """从磁盘加载指定会话。"""
        path = self._file_path(conversation_id)
        if not path.exists():
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            meta_dict = data.get("metadata", {})
            meta = SessionMetadata(
                conversation_id=meta_dict.get("conversation_id", conversation_id),
                created_at=meta_dict.get("created_at", ""),
                updated_at=meta_dict.get("updated_at", ""),
                message_count=meta_dict.get("message_count", 0),
                extra=meta_dict.get("extra", {}),
            )
            return SessionRecord(metadata=meta, messages=data.get("messages", []))
        except Exception as e:
            logger.error(f"Error reading session file {path}: {e}")
            return None

    def list_sessions(self) -> list[SessionMetadata]:
        """列出所有已保存的会话概要。"""
        results: list[SessionMetadata] = []
        for file in self.base_dir.glob("*.json"):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                meta_dict = data.get("metadata", {})
                results.append(
                    SessionMetadata(
                        conversation_id=meta_dict.get("conversation_id", file.stem),
                        created_at=meta_dict.get("created_at", ""),
                        updated_at=meta_dict.get("updated_at", ""),
                        message_count=meta_dict.get("message_count", 0),
                        extra=meta_dict.get("extra", {}),
                    )
                )
            except Exception:
                continue
        # 按更新时间倒序排列
        results.sort(key=lambda s: s.updated_at, reverse=True)
        return results

    def delete(self, conversation_id: str) -> bool:
        """删除指定会话。"""
        path = self._file_path(conversation_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def fork(self, src_id: str, target_id: str) -> SessionRecord | None:
        """分叉会话（以现有会话为模板创建新分支）。"""
        src_record = self.load(src_id)
        if not src_record:
            return None
        return self.save(
            conversation_id=target_id,
            messages=list(src_record.messages),
            extra={"forked_from": src_id},
        )
