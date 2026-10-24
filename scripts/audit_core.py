"""Deterministic two-person reply-interval analysis. Python standard library only."""
from __future__ import annotations

import csv
import hashlib
import html
import json
import math
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = "1.0.0"
REVIEW_STATUSES = ("retained", "restart", "closed", "agreed_deferral", "uncertain", "unreviewed")
STATUS_LABELS = {
    "retained": "上下文支持保留待回应候选",
    "restart": "新话题起点修正后未超过阈值",
    "closed": "旧话题已收尾，未确认仍在等待",
    "agreed_deferral": "明确允许延后回应",
    "uncertain": "证据不足，需人工核对",
    "unreviewed": "尚未审阅",
}
SYSTEM_KINDS = {"system", "系统消息", "拍一拍", "撤回消息", "好友请求", "状态"}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def parse_zone(value):
    if value.upper() in ("UTC", "Z"):
        return timezone.utc
    import re
    m = re.fullmatch(r"([+-])(\d{2}):?(\d{2})", value)
    if not m:
        raise ValueError("timezone 必须是 UTC 或固定偏移，例如 +08:00")
    hours, minutes = int(m[2]), int(m[3])
    if hours > 14 or minutes > 59 or (hours == 14 and minutes):
        raise ValueError("timezone 偏移超出范围")
    return timezone(timedelta(minutes=(hours * 60 + minutes) * (1 if m[1] == "+" else -1)))


def parse_time(value, zone):
    value = str(value).strip()
    if value.replace(".", "", 1).isdigit() and len(value.split(".")[0]) in (10, 13):
        stamp = float(value)
        if len(value.split(".")[0]) == 13:
            stamp /= 1000
        return datetime.fromtimestamp(stamp, zone)
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return t.replace(tzinfo=zone) if t.tzinfo is None else t.astimezone(zone)


def display_time(t):
    return t.isoformat(timespec="seconds")


def duration(value):
    if value is None:
        return "无样本"
    seconds = int(math.floor(value + .5))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}小时{m:02}分{s:02}秒" if h else f"{m}分{s:02}秒"


def read_messages(path, zone, sender_a=None, content=False):
    """Accept canonical CSV/JSON or the documented Chinese CSV adapter; never echo identities."""
    path = Path(path)
    raw_bytes = path.read_bytes()
    if path.suffix.lower() == ".json":
        raw = json.loads(raw_bytes.decode("utf-8-sig"))
        raw = raw.get("messages") if isinstance(raw, dict) else raw
        if not isinstance(raw, list):
            raise ValueError("JSON 必须是消息数组或含 messages 数组的对象")
    elif path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not ({"timestamp", "sender"} <= set(reader.fieldnames or []) or
                    {"时间", "是否我发送", "类型"} <= set(reader.fieldnames or [])):
                raise ValueError("CSV 缺少必需列；见 references/input-format.md")
            raw = list(reader)
    else:
        raise ValueError("只支持已导出的 CSV/JSON，不支持数据库、备份包或媒体文件")
    prepared, identities, conversations = [], [], set()
    excluded, seen, duplicates, missing_conversation = 0, {}, 0, 0
    for index, row in enumerate(raw, 1):
        if not isinstance(row, dict):
            raise ValueError(f"第 {index} 项必须为消息对象")
        kind = str(row.get("kind", row.get("类型", "text"))).strip()
        conversation = str(row.get("conversation_id", row.get("会话", "")) or "").strip()
        if conversation:
            conversations.add(conversation)
        else:
            missing_conversation += 1
        if len(conversations) > 1:
            raise ValueError("输入包含多个会话；请先导出一个双人会话")
        if kind.lower() in SYSTEM_KINDS:
            excluded += 1
            continue
        if "是否我发送" in row:
            direction = str(row["是否我发送"]).strip()
            if direction not in ("是", "否"):
                raise ValueError(f"第 {index} 项发送方向无效")
            identity = "__direction_a__" if direction == "是" else "__direction_b__"
        else:
            identity = str(row.get("sender", "")).strip()
            if not identity:
                raise ValueError(f"第 {index} 项缺少发送方")
        try:
            timestamp = parse_time(row.get("timestamp", row.get("时间", "")), zone)
        except (ValueError, TypeError, OverflowError, OSError):
            raise ValueError(f"第 {index} 项时间格式无效") from None
        if identity not in identities:
            identities.append(identity)
        if len(identities) > 2:
            raise ValueError("有效消息超过两位发送方，不适用于群聊")
        text = str(row.get("text", row.get("内容", "")) or "")
        message_id = str(row.get("message_id", row.get("server_id", "")) or "").strip()
        signature = (display_time(timestamp), identity, kind, hashlib.sha256(text.encode()).hexdigest())
        if message_id and message_id != "0":
            if message_id in seen:
                if seen[message_id] != signature:
                    raise ValueError("同一消息ID对应冲突内容；请核对导出文件")
                duplicates += 1
                continue
            seen[message_id] = signature
        prepared.append({"dt": timestamp, "identity": identity, "kind": kind,
                         "text": text if content else "", "order": index})
    if len(identities) != 2 or len(prepared) < 2:
        raise ValueError("需要两位发送方及至少两条有效消息")
    if "__direction_a__" in identities:
        a = "__direction_a__"
    else:
        a = sender_a if sender_a is not None else identities[0]
    if a not in identities:
        raise ValueError("sender-a 未匹配输入中的发送方")
    prepared.sort(key=lambda m: (m["dt"], m["order"]))
    messages = [{"ref": f"M{i:06}", "time": display_time(m["dt"]),
                 "sender": "A" if m["identity"] == a else "B", "kind": m["kind"],
                 **({"text": m["text"]} if content else {})} for i, m in enumerate(prepared, 1)]
    return messages, {"source_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                      "normalized_sha256": digest([{k:v for k,v in m.items() if k != "text"} for m in messages]), "raw_rows": len(raw),
                      "valid_rows": len(messages), "excluded_system": excluded, "duplicates_removed": duplicates,
                      "conversation_id_missing_rows": missing_conversation,
                      "same_timestamp_adjacent_pairs": sum(x["time"] == y["time"] for x, y in zip(messages, messages[1:]))}


def make_events(messages):
    turns = []
    for message in messages:
        if turns and turns[-1][0]["sender"] == message["sender"]:
            turns[-1].append(message)
        else:
            turns.append([message])
    events = []
    for index, (a, b) in enumerate(zip(turns, turns[1:]), 1):
        first, last, reply = a[0], a[-1], b[0]
        t = datetime.fromisoformat(reply["time"])
        events.append({"event_id": f"E{index:06}", "reply_sender": reply["sender"],
                       "first_ref": first["ref"], "last_ref": last["ref"], "reply_ref": reply["ref"],
                       "first_time": first["time"], "last_time": last["time"], "reply_time": reply["time"],
                       "first_seconds": (t - datetime.fromisoformat(first["time"])).total_seconds(),
                       "last_seconds": (t - datetime.fromisoformat(last["time"])).total_seconds(),
                       "waiting_messages": len(a)})
    return events, turns[-1]


def load_phases(path, zone):
    if path is None:
        return []
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("phases 必须为非空数组")
    result, names = [], set()
    for row in raw:
        name = str(row.get("name", "")).strip()
        if not name or name in names:
            raise ValueError("阶段名称须非空且不重复")
        start, end = parse_time(row["start"], zone), parse_time(row["end"], zone)
        if start >= end:
            raise ValueError("阶段开始必须早于结束；结束时刻不包含在本阶段")
        names.add(name)
        result.append({"name": name, "start": display_time(start), "end": display_time(end)})
    result.sort(key=lambda r: r["start"])
    if any(datetime.fromisoformat(a["end"]) > datetime.fromisoformat(b["start"]) for a, b in zip(result, result[1:])):
        raise ValueError("阶段不能重叠")
    return result


def percentile(values, q):
    if not values:
        return None
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    a, b = math.floor(pos), math.ceil(pos)
    return xs[a] + (xs[b] - xs[a]) * (pos - a)


def summarize(events, sender, metric, short_minutes, thresholds):
    values = [e[metric + "_seconds"] for e in events if e["reply_sender"] == sender]
    short = [v for v in values if v <= short_minutes * 60]
    n = len(values)
    return {"sender": sender, "metric": metric, "count": n,
            "mean_seconds": sum(values) / n if n else None, "median_seconds": percentile(values, .5),
            "p90_seconds": percentile(values, .9), "short_count": len(short),
            "short_mean_seconds": sum(short) / len(short) if short else None,
            "over_counts": {str(v): sum(s > v * 60 for s in values) for v in thresholds},
            "over_rates": {str(v): sum(s > v * 60 for s in values) / n if n else None for v in thresholds}}


def analyze(messages, audit, zone_name="+08:00", phases=None, as_of=None, short_minutes=120,
            thresholds=(120, 180, 240), candidate_minutes=240):
    values = [short_minutes, candidate_minutes, *thresholds]
    if any(not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError("分钟阈值必须为有限正数")
    zone = parse_zone(zone_name)
    cutoff = parse_time(as_of, zone) if as_of else datetime.fromisoformat(messages[-1]["time"])
    if cutoff < datetime.fromisoformat(messages[-1]["time"]):
        raise ValueError("as-of 不得早于输入的最后一条有效消息；请先筛选输入")
    events, tail = make_events(messages)
    config = {"timezone": zone_name, "phases": phases or [], "as_of": display_time(cutoff),
              "short_minutes": short_minutes, "thresholds_minutes": list(thresholds), "candidate_minutes": candidate_minutes}
    group_names = [p["name"] for p in phases] if phases else ["全部记录"]
    groups = {name: [] for name in group_names}
    boundaries = []
    for e in events:
        first, end = datetime.fromisoformat(e["first_time"]), datetime.fromisoformat(e["reply_time"])
        if not phases:
            e["phase"] = "全部记录"
        else:
            matches = [p["name"] for p in phases if parse_time(p["start"], zone) <= first and end < parse_time(p["end"], zone)]
            e["phase"] = matches[0] if matches else None
            touched = [p["name"] for p in phases if first < parse_time(p["end"], zone) and end >= parse_time(p["start"], zone)]
            if not matches and touched:
                boundaries.append({**e, "touching_phases": touched})
        if e["phase"] is not None:
            groups[e["phase"]].append(e)
    selected = [e for e in events if e["phase"] is not None]
    summary = [{"phase": name, **summarize(ev, sender, metric, short_minutes, thresholds)}
               for name, ev in groups.items() for metric in ("first", "last") for sender in ("A", "B")]
    candidates = [e for e in selected if e["first_seconds"] > candidate_minutes * 60]
    candidate_ids = {c["event_id"] for c in candidates}
    assert all(e["event_id"] in candidate_ids for e in selected if e["last_seconds"] > candidate_minutes * 60)
    phase_message_counts = {}
    for name in group_names:
        p = next((p for p in phases or [] if p["name"] == name), None)
        scoped = [m for m in messages if p is None or parse_time(p["start"], zone) <= datetime.fromisoformat(m["time"]) < parse_time(p["end"], zone)]
        phase_message_counts[name] = dict(Counter(m["sender"] for m in scoped))
    pending = {"awaiting_sender": "B" if tail[0]["sender"] == "A" else "A",
               "first_time": tail[0]["time"], "last_time": tail[-1]["time"], "as_of": display_time(cutoff),
               "observed_first_seconds": (cutoff - datetime.fromisoformat(tail[0]["time"])).total_seconds(),
               "complete": False}
    return {"schema_version": VERSION, "analysis_id": digest({"source": audit["source_sha256"], "normalized": audit["normalized_sha256"], "config": config}),
            "audit": audit, "config": config, "phase_message_counts": phase_message_counts, "summary": summary,
            "events": selected, "candidates": candidates, "boundary_events": boundaries, "pending": pending}


def ensure_new_output(path):
    path = Path(path)
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError("输出目录必须不存在或为空，避免覆盖已有报告")
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def csv_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def write_csv(path, rows, fields):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for row in rows:
            w.writerow({k: csv_cell(row.get(k, "")) for k in fields})


def html_table(fields, rows):
    esc = lambda v: html.escape(str(v))
    return '<div class="scroll"><table><thead><tr>' + ''.join('<th>' + esc(k) + '</th>' for k in fields) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join('<td>' + esc(r.get(k, "")) + '</td>' for k in fields) + '</tr>' for r in rows) + '</tbody></table></div>'


def html_document(title, body):
    style = """:root{color-scheme:light dark;--bg:#f5f7f8;--fg:#19303a;--surface:#fff;--line:#dbe4e8;--accent:#176b60;--tint:#e9f4ef}@media(prefers-color-scheme:dark){:root{--bg:#121d23;--fg:#e4edef;--surface:#1a2a32;--line:#354a53;--accent:#8ed6c2;--tint:#263d38}}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.75 system-ui,sans-serif}main{max-width:1100px;margin:35px auto;padding:0 22px 50px}section,article{background:var(--surface);padding:22px;border:1px solid var(--line);border-radius:12px;margin:20px 0}h1{font-size:30px;line-height:1.4}h2{font-size:23px}a{color:var(--accent)}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}th{background:var(--tint)}blockquote{border-left:3px solid var(--accent);margin:16px 0;padding-left:15px;white-space:pre-wrap}summary{cursor:pointer;font-weight:600}.note{border-left:3px solid var(--accent);padding-left:14px}.messages{white-space:pre-wrap}.muted{font-size:14px;opacity:.8}@media(max-width:600px){main{padding:0 12px}section,article{padding:16px}h1{font-size:25px}}"""
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + html.escape(title) + '</title><style>' + style + '</style></head><body><main>' + body + '</main></body></html>'


def write_analysis(out, analysis):
    out = ensure_new_output(out)
    write_json(out / "analysis.json", analysis)
    event_fields = ["event_id", "phase", "reply_sender", "first_time", "last_time", "reply_time", "first_seconds", "last_seconds", "waiting_messages"]
    for name in ("events", "candidates", "boundary_events"):
        write_csv(out / (name + ".csv"), analysis[name], event_fields)
    write_csv(out / "pending.csv", [analysis["pending"]], list(analysis["pending"]))
    rows = []
    for s in analysis["summary"]:
        row = {"阶段": s["phase"], "回复方": s["sender"], "口径": "首条" if s["metric"] == "first" else "末条",
               "事件数": s["count"], "全部平均": duration(s["mean_seconds"]), "中位数": duration(s["median_seconds"]),
               "90分位": duration(s["p90_seconds"]), "短间隔平均": duration(s["short_mean_seconds"])}
        for threshold, count in s["over_counts"].items():
            rate = s["over_rates"][threshold]
            row[f">{threshold}分钟"] = f"{count}次 / {rate:.2%}" if rate is not None else "无样本"
        rows.append(row)
    write_csv(out / "summary.csv", rows, list(rows[0]))
    candidate_rows = [{"事件": e["event_id"], "阶段": e["phase"], "等谁回复": e["reply_sender"],
                       "首条时间": e["first_time"], "下一方发言": e["reply_time"],
                       "首条间隔": duration(e["first_seconds"]), "末条间隔": duration(e["last_seconds"])} for e in analysis["candidates"]]
    caveats = ["这些数字是消息发送时间的交替间隔，不是已读后的反应时间。候选不等于真实待答，更不等于故意不回。",
               "同一方连续消息合为一段：首条口径从本段第一条起算，末条口径从最后一条起算。补发会缩短末条口径。",
               f"短间隔平均仅使用≤{analysis['config']['short_minutes']:g}分钟的事件，不能代替全部样本平均。阈值使用严格大于，各档嵌套，不可相加。",
               "跨阶段事件单列；输入末尾未完成等待另列，不计入已完成平均。未出现消息不代表必须回复或实际失联。",
               "输入中同秒顺序沿用导出顺序，无法恢复更精细先后。去重与文件可读性不证明历史完整。"]
    text = ["# 双人聊天回复间隔统计", "", *["- " + t for t in caveats], "", "| " + " | ".join(rows[0]) + " |", "|" + "|".join("---" for _ in rows[0]) + "|"]
    text += ["| " + " | ".join(str(r[k]) for k in rows[0]) + " |" for r in rows]
    text += ["", f"长间隔候选 {len(candidate_rows)} 次。下一步用 prepare-review 提取上下文；本报告不输出正文。", ""]
    (out / "report.md").write_text("\n".join(text), encoding="utf-8", newline="\n")
    body = '<h1>双人聊天回复间隔统计</h1><p class="note">统计间隔 → 筛选候选 → 上下文审阅。此页不含正文。</p>'
    body += '<section><h2>双方对比</h2>' + html_table(list(rows[0]), rows) + '</section>'
    body += '<section><h2>待审阅的长间隔候选</h2>' + (html_table(list(candidate_rows[0]), candidate_rows) if candidate_rows else '<p>当前范围无候选。</p>') + '</section>'
    body += '<section><h2>如何理解</h2><ul>' + ''.join('<li>' + html.escape(t) + '</li>' for t in caveats) + '</ul><p>固定观察截止：' + html.escape(analysis["config"]["as_of"]) + '</p></section>'
    (out / "report.html").write_text(html_document("回复间隔统计", body), encoding="utf-8", newline="\n")


def prepare_review(messages, audit, analysis, before=8, after=10, max_chars=1200):
    if (audit["source_sha256"] != analysis["audit"]["source_sha256"] or
            audit["normalized_sha256"] != analysis["audit"]["normalized_sha256"]):
        raise ValueError("输入指纹与统计报告不匹配，不能把另一份记录用于复核")
    if before < 0 or after < 1 or max_chars < 1:
        raise ValueError("上下文数量无效")
    by_ref = {m["ref"]: i for i, m in enumerate(messages)}
    packets = []
    for e in analysis["candidates"]:
        i, j = by_ref[e["first_ref"]], by_ref[e["reply_ref"]]
        if (messages[j]["time"] != e["reply_time"] or j - i != e["waiting_messages"] or
                messages[j]["sender"] != e["reply_sender"] or messages[j-1]["time"] != e["last_time"]):
            raise ValueError("候选边界与消息序列不一致")
        context = {}
        for name, seq in (("before", messages[max(0, i-before):i]), ("waiting", messages[i:j]), ("after", messages[j:j+after])):
            context[name] = [{**m, "text": m.get("text", "")[:max_chars], "truncated": len(m.get("text", "")) > max_chars} for m in seq]
        packets.append({"event": e, "context": context})
    return {"schema_version": VERSION, "analysis_id": analysis["analysis_id"],
            "candidate_minutes": analysis["config"]["candidate_minutes"], "contains_private_content": True,
            "scope": "Only the timestamp-screened candidates; no inference of read status or intent.", "cases": packets}


def review_template(packet):
    return {"analysis_id": packet["analysis_id"], "review_source": "human_review",
            "reviews": [{"event_id": c["event"]["event_id"], "status": "unreviewed", "revised_start_ref": None,
                         "basis_refs": [], "reason": "", "context_assessment": "", "context_status": "insufficient"}
                        for c in packet["cases"]]}


def validate_review(case, review, candidate_minutes):
    if not isinstance(review, dict) or review.get("event_id") != case["event"]["event_id"]:
        raise ValueError("复核事件编号不匹配")
    status = review.get("status")
    if status not in REVIEW_STATUSES:
        raise ValueError("未知复核分类")
    refs = {m["ref"]: m for seq in case["context"].values() for m in seq}
    evidence = review.get("basis_refs", [])
    if not isinstance(evidence, list) or any(not isinstance(r, str) or r not in refs for r in evidence):
        raise ValueError("证据引用不在提供的上下文内")
    if status != "unreviewed" and (not isinstance(review.get("reason"), str) or not review["reason"].strip()):
        raise ValueError("已分类事件必须给出理由")
    if status in ("retained", "restart", "closed", "agreed_deferral") and not evidence:
        raise ValueError("确定性分类需要原文引用")
    if status not in ("uncertain", "unreviewed") and any(m.get("truncated") for m in refs.values()):
        raise ValueError("上下文存在截断，须扩大原文或保留不确定")
    start = review.get("revised_start_ref")
    seconds = None
    if status in ("retained", "restart"):
        waiting = {m["ref"]: m for m in case["context"]["waiting"]}
        if start not in waiting:
            raise ValueError("修正起点必须指向本段实际发出的消息")
        seconds = (datetime.fromisoformat(case["event"]["reply_time"]) - datetime.fromisoformat(waiting[start]["time"])).total_seconds()
        if (status == "retained" and seconds <= candidate_minutes*60) or (status == "restart" and seconds > candidate_minutes*60):
            raise ValueError("复核分类与修正后阈值不一致")
    elif start is not None:
        raise ValueError("此分类不应强设一个已确认起点")
    if review.get("context_status", "insufficient") not in ("explained", "possible_context", "no_explanation_visible", "not_applicable", "insufficient"):
        raise ValueError("未知解释状态")
    return {"event_id": review["event_id"], "status": status, "revised_start_ref": start,
            "basis_refs": list(dict.fromkeys(evidence)), "reason": review.get("reason", ""),
            "context_assessment": str(review.get("context_assessment", "")),
            "context_status": review.get("context_status", "insufficient"), "revised_seconds": seconds}


def validate_reviews(packet, annotations, allow_partial=False):
    if annotations.get("analysis_id") != packet["analysis_id"]:
        raise ValueError("复核文件与候选包不匹配")
    source = annotations.get("review_source", "human_review")
    if source not in ("human_review", "model_suggestion", "synthetic_fixture"):
        raise ValueError("未知审阅来源")
    supplied = annotations.get("reviews")
    if not isinstance(supplied, list):
        raise ValueError("reviews 必须为数组")
    cases = {c["event"]["event_id"]: c for c in packet["cases"]}
    result, seen = [], set()
    for r in supplied:
        key = r.get("event_id") if isinstance(r, dict) else None
        if key not in cases or key in seen:
            raise ValueError("复核文件含重复或无关事件")
        seen.add(key)
        result.append(validate_review(cases[key], r, packet["candidate_minutes"]))
    if seen != set(cases):
        if not allow_partial:
            raise ValueError("尚有候选没有复核记录")
        result.extend({"event_id": key, "status": "unreviewed", "basis_refs": [], "reason": "", "context_assessment": "", "context_status": "insufficient", "revised_start_ref": None, "revised_seconds": None} for key in cases if key not in seen)
    if not allow_partial and any(r["status"] == "unreviewed" for r in result):
        raise ValueError("存在未审阅事件；完成后再导出，或明确使用 allow-partial")
    return result, source


def write_review_report(out, packet, annotations, allow_partial=False):
    reviews, source = validate_reviews(packet, annotations, allow_partial)
    out = ensure_new_output(out)
    write_json(out / "validated_reviews.json", {"analysis_id": packet["analysis_id"], "review_source": source, "reviews": reviews})
    cases = {c["event"]["event_id"]: c for c in packet["cases"]}
    counts = {sender: Counter(r["status"] for r in reviews if cases[r["event_id"]]["event"]["reply_sender"] == sender) for sender in ("A", "B")}
    rows = [{"分类": STATUS_LABELS[status], "A": counts["A"][status], "B": counts["B"][status]} for status in REVIEW_STATUSES]
    heading = ("模型审阅建议（尚未人工确认）" if source == "model_suggestion" else
               "虚构样例：预先编写的审阅结果" if source == "synthetic_fixture" else "上下文审阅结果")
    intro = "仅审阅原有长间隔候选。保留项不等于不合理，不确定项不是0次；不能据此推算整个聊天的漏答率或故意冷落。"
    body = '<h1>' + heading + '</h1><p class="note">含对话片段，请在本地保管。</p><p>' + intro + '</p><section><h2>分类汇总</h2>' + html_table(["分类", "A", "B"], rows) + '</section>'
    md = ['# ' + heading, '', intro, '', '此报告含正文；模型结果只是建议，引用校验不等于语义判断正确。', '']
    flat = []
    for r in reviews:
        c, e = cases[r["event_id"]], cases[r["event_id"]]["event"]
        refs = {m["ref"]: m for seq in c["context"].values() for m in seq}
        evidence = [refs[key] for key in r["basis_refs"]]
        measured = duration(r["revised_seconds"]) if r["revised_seconds"] is not None else "不设时长；不是0秒"
        label = STATUS_LABELS[r["status"]]
        flat.append({"event_id": r["event_id"], "reply_sender": e["reply_sender"], "status": r["status"], "revised_seconds": r["revised_seconds"], "reason": r["reason"], "context_assessment": r["context_assessment"]})
        body += '<article><h2>' + e["event_id"] + ' · 等' + e["reply_sender"] + '回复</h2><p><strong>' + label + '</strong></p><p>原首条间隔：' + duration(e["first_seconds"]) + '；起点校准后到下一方发言：' + measured + '</p><p>' + html.escape(r["reason"]) + '</p><p>' + html.escape(r["context_assessment"]) + '</p>'
        body += ''.join('<blockquote>' + html.escape(m["text"]) + '<br><small>' + m["ref"] + ' · ' + html.escape(m["time"]) + ' · ' + m["sender"] + '</small></blockquote>' for m in evidence)
        body += '<details><summary>原文上下文</summary>'
        for name, seq in c["context"].items():
            body += '<h3>' + name + '</h3>' + ''.join('<p class="messages">' + html.escape(m["ref"] + ' ' + m["time"] + ' ' + m["sender"] + '：' + m["text"]) + (' [已截断]' if m["truncated"] else '') + '</p>' for m in seq)
        body += '</details></article>'
        md += ['## ' + e["event_id"] + ' · ' + label, '', '等' + e["reply_sender"] + '回复；校准后：' + measured, '', r["reason"], '', r["context_assessment"], '']
        md += ['> ' + m["ref"] + ' ' + m["sender"] + '：' + m["text"].replace('\n', ' / ') for m in evidence]
        md.append('')
    write_csv(out / "review_summary.csv", flat, ["event_id", "reply_sender", "status", "revised_seconds", "reason", "context_assessment"])
    (out / "report.html").write_text(html_document(heading, body), encoding="utf-8", newline="\n")
    (out / "report.md").write_text('\n'.join(md), encoding="utf-8", newline="\n")
    return reviews
