#!/usr/bin/env python3
"""Local, evidence-first LRC utilities. No network calls or automatic ASR."""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import html
import json
import math
import re
import subprocess
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
TIME_RE = re.compile(r"\[(\d+):([0-5]\d)(?:\.(\d{1,3}))?\]")
META_RE = re.compile(r"^\[([A-Za-z][A-Za-z0-9_-]*):(.*)\]$")
MIME = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".flac": "audio/flac", ".aac": "audio/aac", ".opus": "audio/ogg", ".webm": "audio/webm"}


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def fmt(value: float) -> str:
    if not finite(value) or value < 0:
        raise ValueError("时间必须是非负有限数。")
    cs = int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return f"{cs // 6000:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def rounded(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def local_file(path: str | Path) -> Path:
    result = Path(path).expanduser().resolve()
    if not result.is_file():
        raise ValueError(f"本地文件不存在：{path}")
    return result


def probe_audio(path: str | Path) -> dict[str, Any]:
    source = local_file(path)
    try:
        process = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
             "stream=codec_name,sample_rate,channels,duration:format=duration", "-of", "json", str(source)],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError("找不到 ffprobe。请先安装 FFmpeg 并将其加入 PATH。") from exc
    if process.returncode:
        raise ValueError("ffprobe 无法读取音频：" + process.stderr.strip()[:500])
    result = json.loads(process.stdout)
    streams = result.get("streams", [])
    if not streams:
        raise ValueError("文件没有可用音轨。")
    stream = streams[0]
    raw = result.get("format", {}).get("duration", stream.get("duration"))
    try:
        duration = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("无法确定音频时长。") from exc
    if not finite(duration) or duration <= 0:
        raise ValueError("音频时长必须大于零。")
    return {"name": source.name, "duration": duration, "sha256": sha256_file(source),
            "codec": stream.get("codec_name"), "sample_rate": stream.get("sample_rate"),
            "channels": stream.get("channels")}


def read_text(path: str | Path) -> str:
    return local_file(path).read_text(encoding="utf-8-sig")


def write_text(path: str | Path, content: str, *, force: bool = False, bom: bool = False) -> None:
    target = Path(path)
    if target.exists() and not force:
        raise ValueError(f"输出已存在：{target}。请改名，或明确使用 --force。")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8-sig" if bom else "utf-8")


def load_project(path: str | Path) -> dict[str, Any]:
    data = json.loads(read_text(path))
    require_structure(data)
    return data


def require_structure(data: Any) -> None:
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("不支持的项目格式；需要 schema_version=1。")
    if not isinstance(data.get("entries"), list) or not data["entries"]:
        raise ValueError("entries 必须是非空数组。")
    duration = data.get("duration")
    if not finite(duration) or duration <= 0:
        raise ValueError("duration 必须是正的有限秒数。")
    for field in ("title", "artist", "version"):
        if not isinstance(data.get(field, ""), str) or any(c in data.get(field, "") for c in "\r\n"):
            raise ValueError(f"{field} 必须是单行字符串。")
    for i, row in enumerate(data["entries"], 1):
        if not isinstance(row, dict) or not isinstance(row.get("text"), str):
            raise ValueError(f"第 {i} 项必须包含 text 字符串。")
        if any(c in row["text"] for c in "\r\n"):
            raise ValueError(f"第 {i} 项包含换行；每项只能有一行歌词。")
        if "time" not in row or (row["time"] is not None and not finite(row["time"])):
            raise ValueError(f"第 {i} 项 time 必须是有限秒数或 null。")
        if not isinstance(row.get("verified", False), bool):
            raise ValueError(f"第 {i} 项 verified 必须为布尔值。")
        if not isinstance(row.get("evidence", ""), str):
            raise ValueError(f"第 {i} 项 evidence 必须为字符串。")
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("metadata 必须是对象。")
    for key, value in metadata.items():
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", key):
            raise ValueError("metadata 键只能使用字母、数字、下划线和连字符。")
        if not isinstance(value, str) or any(c in value for c in "\r\n"):
            raise ValueError("metadata 值必须为单行字符串。")


def validate(data: dict[str, Any], expected: list[str] | None = None) -> dict[str, Any]:
    require_structure(data)
    errors: list[str] = []
    warnings: list[str] = []
    duration = data["duration"]
    previous: float | None = None
    previous_row = 0
    timed: list[tuple[int, dict[str, Any]]] = []
    for i, row in enumerate(data["entries"], 1):
        time = row["time"]
        if time is None:
            errors.append(f"第 {i} 项尚未标记时间。")
            continue
        time = rounded(time)
        if time < 0 or time > duration:
            errors.append(f"第 {i} 项时间超出音频范围。")
        if previous is not None and time <= previous:
            errors.append(f"第 {i} 项与第 {previous_row} 项时间重复或倒序（按 LRC 百分秒精度）。")
        if row["text"] and time >= duration:
            errors.append(f"第 {i} 项歌词不能在音频结束后才开始。")
        previous, previous_row = time, i
        timed.append((i, row))
        if row["text"] and not row.get("verified", False):
            warnings.append(f"第 {i} 项尚未标记为试听确认。")
    for (i, row), (_, nxt) in zip(timed, timed[1:]):
        gap = nxt["time"] - row["time"]
        if row["text"] and 0 < gap < 0.35:
            warnings.append(f"第 {i} 项只显示 {gap:.2f} 秒，请检查是否过度挤压。")
        if row["text"] and gap > 18:
            warnings.append(f"第 {i} 项显示超过 18 秒，请核对长音或间奏清屏。")
    if data["entries"][-1]["text"]:
        warnings.append("最后一项仍是歌词；请核对尾奏并按实际唱完位置添加空白清屏项。")
    actual = [row["text"] for row in data["entries"] if row["text"].strip()]
    if expected is not None and actual != expected:
        errors.append("歌词与原稿不一致（逐行、顺序、重复次数和文字均须保留）。")
    verified = sum(bool(row.get("verified")) for row in data["entries"] if row["text"])
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "lyric_lines": len(actual), "timeline_entries": len(data["entries"]),
            "verified_lines": verified, "duration": duration,
            "note": "结构检查不等于听感对齐；verified 仅记录操作者的试听声明。"}


def parse_lrc(text: str, duration: float, offset_mode: str = "reject") -> dict[str, Any]:
    metadata: dict[str, str] = {}
    entries: list[dict[str, Any]] = []
    for line_no, raw in enumerate(text.lstrip("\ufeff").splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        times = []
        pos = 0
        while (match := TIME_RE.match(line, pos)):
            times.append(int(match[1]) * 60 + int(match[2]) + float("0." + (match[3] or "0")))
            pos = match.end()
        if times:
            lyric = line[pos:]
            if re.match(r"\[\d", lyric):
                raise ValueError(f"第 {line_no} 行包含损坏或不支持的时间标签。")
            for time in times:
                entries.append({"time": time, "text": lyric, "verified": False, "evidence": "imported-lrc: needs listening review"})
        else:
            match = META_RE.fullmatch(line)
            if not match:
                raise ValueError(f"第 {line_no} 行不是有效 LRC：{line[:80]}")
            key = match[1].lower()
            if key in metadata:
                raise ValueError(f"元数据标签重复：{key}")
            metadata[key] = match[2]
    if not entries:
        raise ValueError("没有找到歌词时间戳。")
    try:
        offset_ms = int(metadata.get("offset", "0"))
    except ValueError as exc:
        raise ValueError("offset 必须是整数毫秒。") from exc
    if offset_ms and offset_mode == "reject":
        raise ValueError("LRC 含非零 offset。请明确指定 --offset-mode positive-earlier 或 positive-later；不同播放器可能采用不同约定。")
    if offset_ms:
        sign = -1 if offset_mode == "positive-earlier" else 1
        for row in entries:
            row["time"] += sign * offset_ms / 1000
    # Expands repeated tags into chronological entries. Duplicates remain errors, never deleted.
    entries.sort(key=lambda row: row["time"])
    data = {"schema_version": 1, "title": metadata.pop("ti", ""), "artist": metadata.pop("ar", ""),
            "version": metadata.pop("ve", ""), "duration": duration, "entries": entries, "metadata": metadata}
    data["metadata"].pop("offset", None)
    data["metadata"].pop("length", None)
    require_structure(data)
    return data


def export_lrc(data: dict[str, Any], require_verified: bool = False) -> str:
    report = validate(data)
    if not report["ok"]:
        raise ValueError("不能导出：" + "；".join(report["errors"]))
    if require_verified and report["verified_lines"] != report["lyric_lines"]:
        raise ValueError("尚有歌词未试听确认，不能按 --require-verified 导出。")
    header = [f"[ti:{data.get('title', '')}]", f"[ar:{data.get('artist', '')}]", "[by:lrc-sync]"]
    if data.get("version"):
        header.append(f"[ve:{data['version']}]")
    for key, value in data.get("metadata", {}).items():
        if key.lower() not in {"ti", "ar", "by", "ve", "offset", "length"}:
            header.append(f"[{key}:{value}]")
    header.extend([f"[length:{fmt(data['duration'])}]", "[offset:0]", ""])
    return "\n".join(header + [f"[{fmt(row['time'])}]{row['text']}" for row in data["entries"]]) + "\n"


def shift(data: dict[str, Any], delta: float, start: int = 1, end: int | None = None) -> dict[str, Any]:
    require_structure(data)
    if not finite(delta):
        raise ValueError("偏移必须为有限秒数。")
    end = len(data["entries"]) if end is None else end
    if not 1 <= start <= end <= len(data["entries"]):
        raise ValueError("偏移行范围无效（使用 1 开始的时间轴项编号）。")
    result = copy.deepcopy(data)
    for row in result["entries"][start - 1:end]:
        if row["time"] is None:
            raise ValueError("请先为所选范围标记时间。")
        row["time"] = rounded(row["time"] + delta)
        row["verified"] = False
        row["evidence"] = "shifted: needs listening review"
    report = validate(result)
    if not report["ok"]:
        raise ValueError("偏移未应用：" + "；".join(report["errors"]))
    return result


def make_player(data: dict[str, Any], audio: Path | None = None, embed: bool = False) -> str:
    require_structure(data)
    template = Path(__file__).resolve().parent.parent / "assets" / "player.html"
    value = copy.deepcopy(data)
    source = ""
    if audio is not None:
        audio = local_file(audio)
        info = probe_audio(audio)
        if abs(info["duration"] - data["duration"]) > 0.25:
            raise ValueError("音频时长与项目不匹配，可能选错录音版本。")
        if data.get("audio_sha256") and info["sha256"] != data["audio_sha256"]:
            raise ValueError("音频 SHA-256 与项目记录不一致，请勿套用其他录音版本。")
        value["audio_sha256"] = info["sha256"]
        value["audio_name"] = audio.name
        if embed:
            if audio.stat().st_size > 60 * 1024 * 1024:
                raise ValueError("内嵌音频上限为 60 MiB；请使用本地选取音频模式。")
            mime = MIME.get(audio.suffix.lower())
            if not mime:
                raise ValueError("该扩展名不支持内嵌；请使用常见音频格式。")
            source = f"data:{mime};base64," + base64.b64encode(audio.read_bytes()).decode("ascii")
    elif embed:
        raise ValueError("--embed-audio 需要同时提供 --audio。")
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False)
    # Block script termination, HTML injection, and JS line separator hazards.
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    key = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    replacements = {"@@PROJECT@@": payload, "@@KEY@@": key,
                    "@@TITLE@@": html.escape(value.get("title") or "歌词校时"),
                    "@@AUDIO@@": html.escape(source, quote=True)}
    # Single-pass substitution: a title containing another placeholder cannot alter the template.
    return re.sub(r"@@(?:PROJECT|KEY|TITLE|AUDIO)@@", lambda m: replacements[m.group()], template.read_text(encoding="utf-8"))


def new_project(lyrics: str, info: dict[str, Any], title: str, artist: str, version: str) -> dict[str, Any]:
    lines = [line.strip() for line in lyrics.splitlines() if line.strip()]
    if not lines:
        raise ValueError("歌词文件为空。元数据请用参数提供，不要混进歌词正文。")
    return {"schema_version": 1, "title": title, "artist": artist, "version": version,
            "duration": info["duration"], "audio_sha256": info["sha256"], "audio_name": info["name"],
            "metadata": {}, "entries": [{"time": None, "text": line, "verified": False, "evidence": ""} for line in lines]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init", help="从实际音频与原稿创建未标记项目，绝不均分时间")
    p.add_argument("--audio", required=True); p.add_argument("--lyrics", required=True)
    p.add_argument("--title", default=""); p.add_argument("--artist", default=""); p.add_argument("--version", default="")
    p = sub.add_parser("import-lrc", help="导入已有 LRC；原有时间戳全部视为待复核")
    p.add_argument("--lrc", required=True); p.add_argument("--audio", required=True)
    p.add_argument("--offset-mode", choices=["reject", "positive-earlier", "positive-later"], default="reject")
    p = sub.add_parser("validate", help="检查顺序、边界、覆盖率；不承诺听感")
    p.add_argument("project"); p.add_argument("--lyrics"); p.add_argument("--report"); p.add_argument("--require-verified", action="store_true")
    p = sub.add_parser("export", help="导出 UTF-8 BOM LRC")
    p.add_argument("project"); p.add_argument("--require-verified", action="store_true")
    p = sub.add_parser("shift", help="整体或局部偏移；正数延后，负数提前；绝不静默截断")
    p.add_argument("project"); p.add_argument("--seconds", type=float, required=True)
    p.add_argument("--from-entry", type=int, default=1); p.add_argument("--to-entry", type=int)
    p = sub.add_parser("player", help="生成离线试听页；默认不内嵌音频")
    p.add_argument("project"); p.add_argument("--audio"); p.add_argument("--embed-audio", action="store_true")
    for name, p in sub.choices.items():
        p.add_argument("--force", action="store_true", help="明确允许覆盖指定输出")
        if name != "validate":
            p.add_argument("-o", "--output", required=True)
    args = parser.parse_args(argv)
    try:
        command = args.command
        if command == "init":
            data = new_project(read_text(args.lyrics), probe_audio(args.audio), args.title, args.artist, args.version)
        elif command == "import-lrc":
            info = probe_audio(args.audio)
            data = parse_lrc(read_text(args.lrc), info["duration"], args.offset_mode)
            data.update(audio_sha256=info["sha256"], audio_name=info["name"])
        elif command == "validate":
            data = load_project(args.project)
            expected = [line.strip() for line in read_text(args.lyrics).splitlines() if line.strip()] if args.lyrics else None
            report = validate(data, expected)
            if args.require_verified and report["verified_lines"] != report["lyric_lines"]:
                report["errors"].append("存在未试听确认的歌词。")
                report["ok"] = False
            content = json.dumps(report, ensure_ascii=False, indent=2)
            if args.report:
                write_text(args.report, content + "\n", force=args.force)
            print(content)
            return 0 if report["ok"] else 1
        elif command == "export":
            data = load_project(args.project)
            write_text(args.output, export_lrc(data, args.require_verified), force=args.force, bom=True)
            print(f"已导出 {args.output}；{validate(data)['verified_lines']}/{validate(data)['lyric_lines']} 行被标记为试听确认。")
            return 0
        elif command == "shift":
            data = shift(load_project(args.project), args.seconds, args.from_entry, args.to_entry)
        else:
            data = load_project(args.project)
            write_text(args.output, make_player(data, Path(args.audio) if args.audio else None, args.embed_audio), force=args.force)
            print(f"已生成 {args.output}。" + ("包含完整音频，分享前请检查。" if args.embed_audio else "默认需在浏览器中选择本地音频。"))
            return 0
        write_text(args.output, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", force=args.force)
        print(f"已生成 {args.output}。未试听确认的时间戳不能视为精准对齐。")
        return 0
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
