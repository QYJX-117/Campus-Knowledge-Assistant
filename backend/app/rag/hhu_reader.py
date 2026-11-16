"""HHU Markdown reader — cleans navigation keywords from scraped university pages."""

from pathlib import Path
from typing import List

from llama_index.core import Document
from llama_index.core.readers.base import BaseReader

NAV_KEYWORDS = {
    "信息门户", "邮箱", "EN", "首页", "学校概况", "学校简介", "大学章程",
    "历史名人", "历任党政负责人", "现任领导", "院系部门", "院系设置",
    "党政职能部门", "群团组织", "派出机构", "直属单位", "科学研究",
    "科研动态", "学术会议", "科研机构", "科研成果", "学术期刊",
    "管理部门", "信息公告", "教育教学", "师资队伍", "本科生培养",
    "研究生培养", "留学生培养", "终身教育", "人才招聘", "招生就业",
    "本科生招生", "研究生招生", "留学生招生", "就业指导", "合作交流",
    "校园生活", "校园文化", "校园景观", "校园服务", "图书档案",
    "上一篇", "下一篇", "发布时间", "浏览次数", "Top", "Copyright",
}


def clean_hhu_text(text: str) -> str:
    lines = text.split("\n")
    cleaned = []
    nav_streak = 0
    for line in lines:
        stripped = line.strip()
        if not stripped:
            cleaned.append(line)
            continue
        if stripped in NAV_KEYWORDS or len(stripped) <= 2:
            nav_streak += 1
            if nav_streak < 5:
                cleaned.append(line)
        else:
            nav_streak = 0
            cleaned.append(line)
    return _deduplicate("\n".join(cleaned))


def _deduplicate(text: str) -> str:
    lines = text.split("\n")
    seen = set()
    result = []
    for i, line in enumerate(lines):
        key = line.strip().replace("　", "").replace(" ", "")
        if i < 10 and key:
            if key in seen:
                continue
            seen.add(key)
        result.append(line)
    return "\n".join(result)


def parse_frontmatter(content: str) -> tuple[dict, str]:
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    meta = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, parts[2]


class HHUMarkdownReader(BaseReader):
    def load_data(self, file_path: Path | str, **kwargs) -> List[Document]:
        file_path = Path(file_path)
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        meta, body = parse_frontmatter(content)
        body = clean_hhu_text(body)
        if len(body.strip()) < 50:
            return []
        return [Document(
            text=body,
            metadata={
                "title": meta.get("title", file_path.stem),
                "source_url": meta.get("source_url", ""),
                "category": meta.get("category", ""),
                "original_path": meta.get("original_path", ""),
                "file_name": file_path.name,
                "file_path": str(file_path),
            },
        )]

    def load_data_from_directory(self, directory: Path | str, **kwargs) -> List[Document]:
        docs = []
        for md in Path(directory).rglob("*.md"):
            if md.name.lower() in {"readme.md", "index.md"}:
                continue
            docs.extend(self.load_data(md))
        return docs
