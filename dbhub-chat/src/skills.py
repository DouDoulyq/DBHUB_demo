"""Skill 注册表 —— 渐进式披露：系统提示词只含索引，命中触发词时才加载完整 .md。

启动时扫描 .reasonix/skills/ 目录，解析每个 .md 的 YAML 前页。
运行时 detect() 根据用户消息匹配触发词，load() 返回完整正文。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Skill .md 文件所在目录（相对于项目根 — 即 dbhub-chat 的父目录）
SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / ".reasonix" / "skills"

# ── 前页解析 ────────────────────────────────────────────

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> dict:
    """从 Markdown 文本中解析 YAML 前页，返回 dict。"""
    import yaml
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    try:
        return yaml.safe_load(m.group(1)) or {}
    except Exception:
        logger.warning("YAML 前页解析失败，跳过")
        return {}


# ── Skill 模型 ──────────────────────────────────────────


@dataclass
class SkillDef:
    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    file_path: Path | None = None  # .md 文件路径
    _body: str | None = field(default=None, init=False, repr=False)

    def load_body(self) -> str:
        """延迟加载 skill 正文（首次调用时读取文件，自动剥离 YAML 前页）。"""
        if self._body is not None:
            return self._body
        if self.file_path and self.file_path.exists():
            raw = self.file_path.read_text(encoding="utf-8")
            # 剥离 YAML 前页（LLM 不需要看 triggers 等元数据）
            self._body = _FRONTMATTER_RE.sub("", raw, count=1).strip()
            return self._body
        logger.warning("Skill %s 文件不存在: %s", self.name, self.file_path)
        self._body = ""
        return self._body


# ── 注册表 ──────────────────────────────────────────────


class SkillRegistry:
    """管理所有 skill 的发现、触发匹配和加载。"""

    def __init__(self, skills_dir: str | Path | None = None):
        self._dir = Path(skills_dir) if skills_dir else SKILLS_DIR
        self._skills: dict[str, SkillDef] = {}
        self._load_all()

    def _load_all(self) -> None:
        """扫描 skills 目录，解析所有 .md 文件。"""
        if not self._dir.is_dir():
            logger.warning("Skill 目录不存在: %s", self._dir)
            return

        for md_file in sorted(self._dir.glob("*.md")):
            try:
                text = md_file.read_text(encoding="utf-8")
                meta = _parse_frontmatter(text)

                name = meta.get("name", md_file.stem)
                skill = SkillDef(
                    name=name,
                    description=meta.get("description", ""),
                    triggers=meta.get("triggers", []),
                    file_path=md_file,
                )
                self._skills[name] = skill
                logger.info("已加载 skill: %s (%d 个触发词)", name, len(skill.triggers))
            except Exception:
                logger.exception("加载 skill 失败: %s", md_file)

    # ── 公开 API ────────────────────────────────────

    def detect(self, user_message: str) -> list[str]:
        """检测用户消息中触发了哪些 skill，返回 skill name 列表。

        匹配规则：不区分大小写的子串匹配。
        """
        msg_lower = user_message.lower()
        hit: list[str] = []
        for name, skill in self._skills.items():
            for trigger in skill.triggers:
                if trigger.lower() in msg_lower:
                    hit.append(name)
                    break  # 一个 skill 只计一次
        return hit

    def load(self, name: str) -> str:
        """加载指定 skill 的完整 Markdown 正文。"""
        skill = self._skills.get(name)
        if not skill:
            return ""
        return skill.load_body()

    def list_all(self) -> list[SkillDef]:
        """返回所有已注册 skill 的元信息列表。"""
        return list(self._skills.values())

    @property
    def count(self) -> int:
        return len(self._skills)


# ── 全局单例 ────────────────────────────────────────────

_registry: SkillRegistry | None = None


def get_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry
