"""Zero-dependency YAML subset parser for CI/CD pipeline files."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple


class YamlParseError(ValueError):
    """Raised when a YAML document cannot be parsed."""


@dataclass
class _Line:
    lineno: int
    indent: int
    text: str


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for idx, ch in enumerate(line):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_double:
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if idx == 0 or line[idx - 1].isspace():
                return line[:idx].rstrip()
    return line.rstrip()


def _parse_scalar(raw: str) -> Any:
    val = raw.strip()
    if val == "" or val in ("null", "Null", "NULL", "~"):
        return None
    if val in ("true", "True", "TRUE"):
        return True
    if val in ("false", "False", "FALSE"):
        return False
    if (val.startswith('"') and val.endswith('"')) or (
        val.startswith("'") and val.endswith("'")
    ):
        if len(val) >= 2:
            inner = val[1:-1]
            if val.startswith('"'):
                inner = inner.replace('\\"', '"').replace("\\n", "\n")
            return inner
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part) for part in _split_inline(inner)]
    if val.startswith("{") and val.endswith("}"):
        inner = val[1:-1].strip()
        if not inner:
            return {}
        result = {}
        for part in _split_inline(inner):
            if ":" in part:
                k, v = part.split(":", 1)
                result[_parse_scalar(k)] = _parse_scalar(v)
        return result
    try:
        if val.startswith("0") and len(val) > 1 and val[1].isdigit():
            return val
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def _split_inline(text: str) -> List[str]:
    parts: List[str] = []
    current: List[str] = []
    in_single = False
    in_double = False
    depth = 0
    for ch in text:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth = max(0, depth - 1)
            elif ch == "," and depth == 0:
                parts.append("".join(current).strip())
                current = []
                continue
        current.append(ch)
    if current:
        parts.append("".join(current).strip())
    return parts


def _split_key_value(text: str) -> Optional[Tuple[str, str]]:
    in_single = False
    in_double = False
    for idx, ch in enumerate(text):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == ":" and not in_single and not in_double:
            if idx + 1 == len(text) or text[idx + 1].isspace():
                key = text[:idx].strip()
                rest = text[idx + 1 :].strip()
                if (key.startswith('"') and key.endswith('"')) or (
                    key.startswith("'") and key.endswith("'")
                ):
                    key = key[1:-1]
                return key, rest
    return None


def _tokenize(content: str) -> List[_Line]:
    lines: List[_Line] = []
    for idx, raw_line in enumerate(content.splitlines(), start=1):
        if raw_line.strip() in ("---", "..."):
            continue
        cleaned = _strip_comment(raw_line)
        if not cleaned.strip():
            continue
        indent = len(cleaned) - len(cleaned.lstrip(" "))
        lines.append(_Line(lineno=idx, indent=indent, text=cleaned.lstrip(" ")))
    return lines


def _parse_block(lines: List[_Line], pos: int, min_indent: int) -> Tuple[Any, int]:
    if pos >= len(lines):
        return None, pos
    current = lines[pos]
    if current.text.startswith("- ") or current.text == "-":
        return _parse_list(lines, pos, current.indent)
    if _split_key_value(current.text) is not None:
        return _parse_dict(lines, pos, current.indent)
    return _parse_scalar(current.text), pos + 1


def _parse_multiline_scalar(
    lines: List[_Line], pos: int, parent_indent: int, fold: bool
) -> Tuple[str, int]:
    chunks: List[str] = []
    block_indent: Optional[int] = None
    while pos < len(lines):
        line = lines[pos]
        if line.indent <= parent_indent:
            break
        if block_indent is None:
            block_indent = line.indent
        chunks.append(line.text)
        pos += 1
    joiner = " " if fold else "\n"
    return joiner.join(chunks), pos


def _parse_list(lines: List[_Line], pos: int, list_indent: int) -> Tuple[List[Any], int]:
    items: List[Any] = []
    while pos < len(lines):
        line = lines[pos]
        if line.indent < list_indent:
            break
        if line.indent > list_indent:
            raise YamlParseError(f"Unexpected indentation at line {line.lineno}")
        if not (line.text.startswith("- ") or line.text == "-"):
            break

        after_dash = line.text[1:].strip() if line.text == "-" else line.text[2:].strip()
        pos += 1

        if not after_dash:
            if pos < len(lines) and lines[pos].indent > list_indent:
                val, pos = _parse_block(lines, pos, list_indent + 1)
                items.append(val)
            else:
                items.append(None)
            continue

        if after_dash in ("|", ">"):
            val, pos = _parse_multiline_scalar(
                lines, pos, list_indent, fold=(after_dash == ">")
            )
            items.append(val)
            continue

        kv = _split_key_value(after_dash)
        if kv is not None:
            key, val_str = kv
            item_dict: dict[str, Any] = {}
            if val_str in ("|", ">"):
                val, pos = _parse_multiline_scalar(
                    lines, pos, list_indent, fold=(val_str == ">")
                )
                item_dict[key] = val
            elif val_str == "":
                if pos < len(lines) and lines[pos].indent > list_indent + 1:
                    val, pos = _parse_block(lines, pos, list_indent + 2)
                    item_dict[key] = val
                else:
                    item_dict[key] = None
            else:
                item_dict[key] = _parse_scalar(val_str)

            if pos < len(lines) and lines[pos].indent > list_indent:
                extra, pos = _parse_dict(lines, pos, lines[pos].indent)
                if isinstance(extra, dict):
                    item_dict.update(extra)
            items.append(item_dict)
        else:
            items.append(_parse_scalar(after_dash))

    return items, pos


def _parse_dict(lines: List[_Line], pos: int, dict_indent: int) -> Tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while pos < len(lines):
        line = lines[pos]
        if line.indent < dict_indent:
            break
        if line.indent > dict_indent:
            raise YamlParseError(f"Unexpected indentation at line {line.lineno}")
        if line.text.startswith("- ") or line.text == "-":
            break

        kv = _split_key_value(line.text)
        if kv is None:
            raise YamlParseError(f"Expected key: value at line {line.lineno}: {line.text}")
        key, val_str = kv
        pos += 1

        if val_str in ("|", ">"):
            val, pos = _parse_multiline_scalar(
                lines, pos, dict_indent, fold=(val_str == ">")
            )
            result[key] = val
        elif val_str == "":
            if pos < len(lines) and lines[pos].indent > dict_indent:
                val, pos = _parse_block(lines, pos, dict_indent + 1)
                result[key] = val
            else:
                result[key] = None
        else:
            result[key] = _parse_scalar(val_str)

    return result, pos


def load_yaml_subset(content: str) -> Any:
    """Parse a YAML subset string into Python objects."""
    lines = _tokenize(content)
    if not lines:
        return {}
    data, _ = _parse_block(lines, 0, 0)
    return data
