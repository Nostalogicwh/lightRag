#!/usr/bin/env python3
import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def build_path_key(parts: list[str]) -> str:
    return " > ".join([normalize(p) for p in parts if normalize(p)])


def note_is_remove(note: str) -> bool:
    text = (note or "").strip()
    return any(
        marker in text
        for marker in (
            "这个不要",
            "这个不需要",
            "不需要了",
            "不需要",
            "这个不要了",
            "不涉及",
            "无关",
            "可删除",
            "删除",
            "错",
        )
    )


def split_name_value(raw_name: str) -> tuple[str, str]:
    text = (raw_name or "").strip()
    for sep in ("：", "﹕", "∶", ":"):
        if sep in text:
            left, right = text.split(sep, 1)
            return left.strip(), right.strip()
    return text, ""


def infer_source(value_text: str, note_text: str) -> str:
    merged = f"{value_text} {note_text}".strip()
    if any(
        token in merged
        for token in ("用户录入", "用户输入", "用户提供", "客户录入", "客户输入", "客户提供")
    ):
        return "user_input"
    if any(token in merged for token in ("计算", "公式", "%", "×", "*", "sqrt", "根3")):
        return "formula"
    if "默认" in merged:
        return "default"
    return "standard"


def extract_corrected_value_text(note_text: str) -> str:
    text = (note_text or "").strip()
    if not text:
        return ""
    markers = ("应当为", "应改为", "应改成", "应该为", "应为", "改为", "改成", "修改为")
    for marker in markers:
        idx = text.find(marker)
        if idx < 0:
            continue
        corrected = text[idx + len(marker) :].strip()
        corrected = re.sub(r"^[：:，,。.、\-\s]+", "", corrected)
        if corrected:
            return corrected
    return ""


def resolve_value_text(value_text: str, note_text: str, value_source: str) -> str:
    note_text = (note_text or "").strip()
    if value_source == "user_input":
        for token in ("用户录入", "用户输入", "用户提供", "客户录入", "客户输入", "客户提供"):
            idx = note_text.find(token)
            if idx >= 0:
                user_text = note_text[idx:]
                return re.sub(r"^[：:，,。.、\-\s]+", "", user_text).strip()
    corrected_text = extract_corrected_value_text(note_text)
    if corrected_text:
        return corrected_text
    if note_text:
        return note_text
    return (value_text or "").strip()


def extract_corrected_param_name(note_text: str) -> str:
    text = (note_text or "").strip()
    if not text:
        return ""
    patterns = (
        r"(?:特征值名称错误|参数名称错误|名称错误)[，,:： ]*(?:应当为|应为|改为|修改为)([^，,。；;]+)",
        r"(?:应当为|应为|改为|修改为)([^，,。；;]+)",
    )
    for pattern in patterns:
        matched = re.search(pattern, text)
        if not matched:
            continue
        name = (matched.group(1) or "").strip()
        name = re.sub(r"^[：:，,。.、\-\s]+", "", name)
        if name:
            return name
    return ""


def resolve_param_name(param_name: str, note_text: str) -> str:
    corrected_name = extract_corrected_param_name(note_text)
    if corrected_name:
        return corrected_name
    return (param_name or "").strip()


def extract_missing_feature_params(note_text: str) -> list[tuple[str, str]]:
    text = (note_text or "").strip()
    if not text:
        return []
    items: list[tuple[str, str]] = []
    segments = [seg.strip() for seg in re.split(r"[；;\n]+", text) if seg.strip()]
    for segment in segments:
        if "缺特征值" not in segment and "缺少特征值" not in segment:
            continue
        matched = re.search(r"缺(?:少)?特征值[：:]\s*(.+)", segment)
        payload = matched.group(1).strip() if matched else ""
        if not payload:
            continue
        payload = re.sub(r"^[:：，,\s]+", "", payload).strip()
        if not payload:
            continue
        param_name = ""
        value_hint = ""
        for sep in ("，", ",", ":", "："):
            if sep in payload:
                left, right = payload.split(sep, 1)
                if left.strip():
                    param_name = left.strip()
                    value_hint = right.strip()
                    break
        if not param_name:
            param_name = payload
        items.append((param_name, value_hint))
    return items


def extract_missing_test_items(note_text: str) -> list[tuple[str, str]]:
    text = (note_text or "").strip()
    if not text:
        return []
    items: list[tuple[str, str]] = []
    for matched in re.finditer(r"缺(?:少)?([^\s，,；;。]*(?:试验|试验\([^)]+\)))", text):
        test_name = (matched.group(1) or "").strip()
        if not test_name:
            continue
        detail = ""
        tail = text[matched.end() :]
        detail_matched = re.search(
            r"(?:全量)?特征值(?:应该)?为\s*([^)；;。]+(?:\([^)]*\)[^)；;。]*)?)", tail
        )
        if not detail_matched:
            detail_matched = re.search(r"特征值[，,:：]\s*(.+?)\s*(?:；|。|$)", tail)
        if detail_matched:
            detail = detail_matched.group(1).strip()
        items.append((test_name, detail))
    return items


def extract_test_item_detail_params(detail_text: str) -> list[tuple[str, str]]:
    text = (detail_text or "").strip()
    if not text:
        return []
    text = re.sub(r"^(?:全量)?特征值(?:应该)?为", "", text).strip()
    if not text:
        return []
    if all(token not in text for token in ("（", "）", "(", ")", "，", ",", ":")):
        return [(seg.strip(), "") for seg in re.split(r"[、；;\n]+", text) if seg.strip()]
    if all(token not in text for token in ("（", "）", "(", ")", ":")) and "、" in text:
        list_like = [seg.strip() for seg in re.split(r"[、，,；;\n]+", text) if seg.strip()]
        if len(list_like) >= 2:
            return [(seg, "") for seg in list_like]
    params: list[tuple[str, str]] = []
    for segment in re.split(r"[、；;\n]+", text):
        seg = segment.strip().strip("，,。")
        if not seg:
            continue
        param_name = seg
        value_text = ""
        if "（" in seg and "）" in seg:
            left, right = seg.split("（", 1)
            param_name = left.strip()
            value_text = right.rsplit("）", 1)[0].strip()
        elif "(" in seg and ")" in seg:
            left, right = seg.split("(", 1)
            param_name = left.strip()
            value_text = right.rsplit(")", 1)[0].strip()
        elif "，" in seg:
            left, right = seg.split("，", 1)
            param_name = left.strip()
            value_text = right.strip()
        elif "," in seg:
            left, right = seg.split(",", 1)
            param_name = left.strip()
            value_text = right.strip()
        if "（" in param_name and "）" in param_name:
            param_name = param_name.split("（", 1)[0].strip()
        if "(" in param_name and ")" in param_name:
            param_name = param_name.split("(", 1)[0].strip()
        params.append((param_name, value_text))
    return params


def normalize_rules_payload(payload: dict[str, Any]) -> dict[str, Any]:
    tests_by_path: dict[str, dict[str, Any]] = {}
    tests_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    add_test_items: list[dict[str, Any]] = []

    if isinstance(payload.get("tests_by_path"), dict):
        for path_key, raw_rule in payload.get("tests_by_path", {}).items():
            if not isinstance(raw_rule, dict):
                continue
            rule = dict(raw_rule)
            test_name = str(rule.get("test_name", "") or rule.get("test_item", "") or "").strip()
            category = str(rule.get("category", "") or "").strip()
            report_type = str(rule.get("report_type", "") or "").strip()
            if not test_name:
                parts = [p.strip() for p in str(path_key).split(">") if p.strip()]
                if parts:
                    test_name = parts[-1]
                if len(parts) >= 2 and not category:
                    category = parts[-2]
                if len(parts) >= 3 and not report_type:
                    report_type = parts[0]
            normalized_path = build_path_key([report_type, category, test_name])
            if not normalized_path:
                normalized_path = build_path_key([str(path_key)])
            rule["test_name"] = test_name
            rule["category"] = category
            rule["report_type"] = report_type
            rule["path_key"] = normalized_path
            rule.setdefault("parameters", [])
            rule.setdefault("remove_parameters", [])
            rule.setdefault("remove_rules", [])
            tests_by_path[normalized_path] = rule

    if isinstance(payload.get("tests_by_name"), dict):
        for _, raw_rules in payload.get("tests_by_name", {}).items():
            if isinstance(raw_rules, dict):
                raw_rules = [raw_rules]
            if not isinstance(raw_rules, list):
                continue
            for raw_rule in raw_rules:
                if not isinstance(raw_rule, dict):
                    continue
                rule = dict(raw_rule)
                test_name = str(rule.get("test_name", "") or "").strip()
                key = normalize(test_name)
                if key:
                    tests_by_name[key].append(rule)

    if isinstance(payload.get("add_test_items"), list):
        add_test_items.extend(
            [item for item in payload.get("add_test_items", []) if isinstance(item, dict)]
        )

    if tests_by_path:
        for rule in tests_by_path.values():
            name_key = normalize(str(rule.get("test_name", "") or ""))
            if name_key:
                tests_by_name[name_key].append(rule)

    return {
        "tests_by_path": tests_by_path,
        "tests_by_name": dict(tests_by_name),
        "add_test_items": add_test_items,
    }


def extract_rules_from_tree_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if any(isinstance(payload.get(k), (dict, list)) for k in ("tests_by_path", "add_test_items", "tests_by_name")):
        return normalize_rules_payload(payload)

    root = payload.get("tree", payload)
    if not isinstance(root, dict):
        return {"tests_by_path": {}, "tests_by_name": {}, "add_test_items": []}

    tests_by_path: dict[str, dict[str, Any]] = {}
    tests_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    add_test_items: list[dict[str, Any]] = []
    add_seen: set[str] = set()

    def walk(node: dict[str, Any], ancestors: list[str]) -> None:
        node_name = str(node.get("name", "") or "").strip()
        node_note = str(node.get("note", "") or "").strip()
        children = node.get("children", [])
        if not isinstance(children, list):
            children = []
        current_path = [*ancestors, node_name] if node_name else list(ancestors)

        if node_name and len(current_path) == 2 and node_note:
            report_name = str(current_path[0]).strip()
            category_name = str(current_path[-1]).strip()
            for missing_test_name, detail in extract_missing_test_items(node_note):
                add_key = build_path_key([report_name, category_name, missing_test_name])
                if not add_key or add_key in add_seen:
                    continue
                add_seen.add(add_key)
                params_payload = []
                for param_name, value_text in extract_test_item_detail_params(detail):
                    value_source = infer_source(value_text, value_text)
                    resolved_value_text = resolve_value_text(value_text, value_text, value_source)
                    params_payload.append(
                        {
                            "param_name": param_name,
                            "value_text": resolved_value_text,
                            "value_expr": value_text if value_source in {"user_input", "formula", "default"} else "",
                            "value_source": value_source,
                            "value_type": value_source,
                            "constraints": value_text,
                            "calc_rule": value_text if value_source == "formula" else "",
                            "derive_from_rated": value_text if value_source == "user_input" else "",
                        }
                    )
                add_test_items.append(
                    {
                        "test_item": missing_test_name,
                        "category": category_name,
                        "report_type": report_name,
                        "aliases": [],
                        "acceptance_criteria": "",
                        "note": node_note,
                        "confidence": 1.0,
                        "required_reports": [{"report_type": report_name, "is_required": True, "condition": ""}],
                        "parameters": params_payload,
                        "rules": [],
                    }
                )

        feature_node = None
        for child in children:
            if isinstance(child, dict) and str(child.get("name", "")).strip() == "特征值":
                feature_node = child
                break

        parent_name = current_path[-2] if len(current_path) >= 2 else ""
        is_test_level_node = len(current_path) >= 3 and parent_name != "特征值"
        if node_name and is_test_level_node and (feature_node is not None or note_is_remove(node_note)):
            report_name = str(current_path[0]).strip() if current_path else ""
            category_name = current_path[-2] if len(current_path) >= 2 else ""
            path_key = build_path_key([report_name, category_name, node_name])
            rule = {
                "test_name": node_name,
                "report_type": report_name,
                "category": category_name,
                "path_parts": current_path,
                "path_key": path_key,
                "skip": note_is_remove(node_note),
                "note": node_note,
                "parameters": [],
                "remove_parameters": [],
                "remove_rules": [],
            }
            if feature_node is not None:
                feature_note = str(feature_node.get("note", "") or "").strip()
                param_nodes = feature_node.get("children", [])
                if isinstance(param_nodes, list):
                    for param_node in param_nodes:
                        if not isinstance(param_node, dict):
                            continue
                        param_raw_name = str(param_node.get("name", "") or "").strip()
                        param_note = str(param_node.get("note", "") or "").strip()
                        if not param_raw_name:
                            continue
                        param_name, value_text = split_name_value(param_raw_name)
                        if note_is_remove(param_note):
                            if param_name:
                                rule["remove_parameters"].append(param_name)
                            continue
                        resolved_param_name = resolve_param_name(param_name, param_note)
                        value_source = infer_source(value_text, param_note)
                        resolved_value_text = resolve_value_text(value_text, param_note, value_source)
                        value_expr = param_note if value_source in {"user_input", "formula", "default"} and param_note else ""
                        rule["parameters"].append(
                            {
                                "param_name": resolved_param_name,
                                "value_text": resolved_value_text,
                                "value_expr": value_expr,
                                "value_source": value_source,
                                "value_type": value_source,
                                "constraints": param_note,
                                "calc_rule": param_note if value_source == "formula" else "",
                                "derive_from_rated": param_note if value_source == "user_input" else "",
                            }
                        )

                existing_param_keys = {
                    normalize(str(param.get("param_name", "") or ""))
                    for param in rule["parameters"]
                    if isinstance(param, dict)
                }
                existing_remove_keys = {
                    normalize(str(name)) for name in rule["remove_parameters"] if normalize(str(name))
                }
                for missing_param_name, value_hint in extract_missing_feature_params(feature_note):
                    missing_key = normalize(missing_param_name)
                    if not missing_key or missing_key in existing_remove_keys or missing_key in existing_param_keys:
                        continue
                    if note_is_remove(value_hint):
                        rule["remove_parameters"].append(missing_param_name)
                        existing_remove_keys.add(missing_key)
                        continue
                    value_source = infer_source(value_hint, value_hint)
                    resolved_value_text = resolve_value_text(value_hint, value_hint, value_source)
                    rule["parameters"].append(
                        {
                            "param_name": missing_param_name,
                            "value_text": resolved_value_text,
                            "value_expr": value_hint if value_source in {"user_input", "formula", "default"} else "",
                            "value_source": value_source,
                            "value_type": value_source,
                            "constraints": value_hint,
                            "calc_rule": value_hint if value_source == "formula" else "",
                            "derive_from_rated": value_hint if value_source == "user_input" else "",
                        }
                    )

            if path_key:
                tests_by_path[path_key] = rule
            tests_by_name[normalize(node_name)].append(rule)

        for child in children:
            if isinstance(child, dict):
                walk(child, current_path)

    walk(root, [])
    return {
        "tests_by_path": tests_by_path,
        "tests_by_name": dict(tests_by_name),
        "add_test_items": add_test_items,
    }


def merge_rules(base_rules: dict[str, Any], patch_rules: dict[str, Any]) -> dict[str, Any]:
    merged = {
        "tests_by_path": dict(base_rules.get("tests_by_path", {}) or {}),
        "tests_by_name": dict(base_rules.get("tests_by_name", {}) or {}),
        "add_test_items": list(base_rules.get("add_test_items", []) or []),
    }

    for path_key, raw_patch_rule in (patch_rules.get("tests_by_path", {}) or {}).items():
        if not isinstance(raw_patch_rule, dict):
            continue
        patch_rule = dict(raw_patch_rule)
        existing_rule = merged["tests_by_path"].get(path_key)
        if not isinstance(existing_rule, dict):
            merged["tests_by_path"][path_key] = patch_rule
            continue
        combined_rule = dict(existing_rule)
        for top_key in (
            "test_name",
            "category",
            "report_type",
            "path_parts",
            "path_key",
            "note",
            "aliases",
            "acceptance_criteria",
            "required_reports",
            "parameters_mode",
            "template_only",
            "skip",
        ):
            if top_key in patch_rule and patch_rule.get(top_key) not in (None, ""):
                combined_rule[top_key] = patch_rule.get(top_key)

        remove_seen = {
            normalize(str(name))
            for name in (existing_rule.get("remove_parameters", []) or [])
            if normalize(str(name))
        }
        remove_params = list(existing_rule.get("remove_parameters", []) or [])
        for raw_name in patch_rule.get("remove_parameters", []) or []:
            key = normalize(str(raw_name))
            if key and key not in remove_seen:
                remove_seen.add(key)
                remove_params.append(raw_name)
        combined_rule["remove_parameters"] = remove_params

        existing_params = list(existing_rule.get("parameters", []) or [])
        index_by_key: dict[str, int] = {}
        for idx, raw_param in enumerate(existing_params):
            if not isinstance(raw_param, dict):
                continue
            key = normalize(str(raw_param.get("param_key", "") or raw_param.get("param_name", "")))
            if key:
                index_by_key[key] = idx
        for raw_patch_param in patch_rule.get("parameters", []) or []:
            if not isinstance(raw_patch_param, dict):
                continue
            patch_param = dict(raw_patch_param)
            key = normalize(str(patch_param.get("param_key", "") or patch_param.get("param_name", "")))
            if key and key in index_by_key:
                merged_param = dict(existing_params[index_by_key[key]])
                merged_param.update(patch_param)
                existing_params[index_by_key[key]] = merged_param
            else:
                existing_params.append(patch_param)
                if key:
                    index_by_key[key] = len(existing_params) - 1
        combined_rule["parameters"] = existing_params
        merged["tests_by_path"][path_key] = combined_rule

    add_items = list(merged.get("add_test_items", []) or [])
    add_index: dict[str, int] = {}
    for idx, item in enumerate(add_items):
        if not isinstance(item, dict):
            continue
        k = build_path_key(
            [
                str(item.get("report_type", "") or ""),
                str(item.get("category", "") or ""),
                str(item.get("test_item", "") or item.get("test_name", "") or ""),
            ]
        )
        if k:
            add_index[k] = idx

    for raw_patch_add in patch_rules.get("add_test_items", []) or []:
        if not isinstance(raw_patch_add, dict):
            continue
        patch_add = dict(raw_patch_add)
        k = build_path_key(
            [
                str(patch_add.get("report_type", "") or ""),
                str(patch_add.get("category", "") or ""),
                str(patch_add.get("test_item", "") or patch_add.get("test_name", "") or ""),
            ]
        )
        if k and k in add_index:
            merged_add = dict(add_items[add_index[k]])
            merged_add.update(patch_add)
            existing_params = list(add_items[add_index[k]].get("parameters", []) or [])
            param_index: dict[str, int] = {}
            for idx, raw_param in enumerate(existing_params):
                if not isinstance(raw_param, dict):
                    continue
                key = normalize(str(raw_param.get("param_key", "") or raw_param.get("param_name", "")))
                if key:
                    param_index[key] = idx
            for raw_patch_param in patch_add.get("parameters", []) or []:
                if not isinstance(raw_patch_param, dict):
                    continue
                patch_param = dict(raw_patch_param)
                key = normalize(str(patch_param.get("param_key", "") or patch_param.get("param_name", "")))
                if key and key in param_index:
                    merged_param = dict(existing_params[param_index[key]])
                    merged_param.update(patch_param)
                    existing_params[param_index[key]] = merged_param
                else:
                    existing_params.append(patch_param)
                    if key:
                        param_index[key] = len(existing_params) - 1
            merged_add["parameters"] = existing_params
            add_items[add_index[k]] = merged_add
        else:
            add_items.append(patch_add)
            if k:
                add_index[k] = len(add_items) - 1

    merged["add_test_items"] = add_items

    tests_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rule in (merged.get("tests_by_path", {}) or {}).values():
        if not isinstance(rule, dict):
            continue
        name_key = normalize(str(rule.get("test_name", "") or ""))
        if name_key:
            tests_by_name[name_key].append(rule)
    merged["tests_by_name"] = dict(tests_by_name)
    return merged


def _sanitize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    def _clean_text(raw: str) -> str:
        text = str(raw or "").strip()
        if not text:
            return text
        text = re.sub(r"没有抓全[，,。；;]*", "", text)
        text = re.sub(r"缺少隔离断口[，,。；;]*", "", text)
        text = re.sub(r"^连续两个[^，,。]*[，,]\s*并且有条件", "", text)
        text = re.sub(r"^连续两个[^，,。]*", "", text)
        if "并且有条件" in text:
            text = text.split("并且有条件", 1)[1]
        text = re.sub(r"^[，,。；;\s]+", "", text)
        text = re.sub(r"(\d+\s*min)\s+min\b", r"\1", text, flags=re.I)
        text = re.sub(r"(\d+\s*ms)\s+ms\b", r"\1", text, flags=re.I)
        text = re.sub(r"(\d+\s*kV)\s+kV\b", r"\1", text, flags=re.I)
        text = re.sub(r"(\d+\s*kA)\s+kA\b", r"\1", text, flags=re.I)
        text = re.sub(r"(\d+\s*pC)\s+pC\b", r"\1", text, flags=re.I)
        text = re.sub(r"\b(kV|Hz|min|ms|kA|A|V|pC|次|相)\s+\1\b", r"\1", text, flags=re.I)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, sub_value in list(value.items()):
                if key in {"value_text", "value_expr", "constraints"} and isinstance(sub_value, str):
                    value[key] = _clean_text(sub_value)
                else:
                    _walk(sub_value)
        elif isinstance(value, list):
            for item in value:
                _walk(item)

    _walk(payload)

    # Domain-specific corrections for slash-mixed values introduced by noisy extraction.
    for rule in (payload.get("tests_by_path", {}) or {}).values():
        if not isinstance(rule, dict):
            continue
        for param in (rule.get("parameters", []) or []):
            if not isinstance(param, dict):
                continue
            param_name = str(param.get("param_name", "") or "")
            value_text = str(param.get("value_text", "") or "")
            if "/" not in value_text:
                continue
            left, right = [part.strip() for part in value_text.split("/", 1)]
            if "试验次数" in param_name and left.startswith("应满足"):
                if re.search(r"^\d+(?:\.\d+)?$", right):
                    param["value_text"] = right
                    param["value_expr"] = right
                    param["constraints"] = right
                continue
            if "试验次数" in param_name and "工频相应次数" in left:
                right_num = re.search(r"(\d+(?:\.\d+)?)", right)
                if right_num:
                    normalized = right_num.group(1)
                    param["value_text"] = normalized
                    param["value_expr"] = normalized
                    param["constraints"] = normalized
                continue
            if "试验电压" in param_name and left.startswith("应符合"):
                # Keep normative clause text, avoid forcing a fixed voltage value.
                param["value_text"] = left
                param["value_expr"] = left
                param["constraints"] = left
                continue

    canonical_overrides: dict[tuple[str, str], str] = {
        ("型式试验 > 绝缘性能型式试验 > 工频耐受电压试验", "试验部位"): "极对地、极间、开关断口",
        (
            "型式试验 > 绝缘性能型式试验 > 工频耐受电压试验",
            "交流电压",
        ): "按额定电压选取（通用/隔离）：3.6kV=25/27，7.2kV=30/34，12kV=42/48，24kV=50/64或65/79，40.5kV=95/118，72.5kV=140/160（断口+42），126kV=185/230（断口+73），252kV=395/460（断口+146），363kV=460/510（断口+210），550kV=680/740（断口+318），800kV=900/960（断口+462），1100kV=1100（断口+635）kV。",
        ("型式试验 > 绝缘性能型式试验 > 雷电冲击耐受电压试验", "试验部位"): "极对地、极间、开关断口",
        (
            "型式试验 > 绝缘性能型式试验 > 雷电冲击耐受电压试验",
            "雷电冲击干耐受电压",
        ): "按额定电压选取（通用/隔离）：3.6kV=40/46，7.2kV=60/70，12kV=75/85，24kV=95/115或125/145，40.5kV=185/215，72.5kV=325/380（断口+59），126kV=450/550（断口+103），252kV=950/1050（断口+206），363kV=1050/1175（断口+205），550kV=1550/1675（断口+315），800kV=1950/2100（断口+455），1100kV=2250/2400（断口+630）kV。",
        ("型式试验 > 绝缘性能型式试验 > 操作冲击耐受电压试验", "试验部位"): "极对地、极间、开关断口",
        (
            "型式试验 > 绝缘性能型式试验 > 操作冲击耐受电压试验",
            "操作冲击耐受电压",
        ): "额定电压范围II按表4选取：363kV（极对地和开关断口850/950，极间1300/1425，隔离断口850(+295)/950(+295)），550kV（1175/1300，1800/1950，1050(+450)/1175(+450)），800kV（1425/1550，2550/2700，1300(+650)/1425(+650)），1100kV（1675/1800，2700/2900，1550(+900)/1675(+900)）kV。",
    }
    insulation_rated_voltage = (
        "额定电压范围I：3.6、7.2、12、24、40.5、72.5、126、252 kV；"
        "额定电压范围II：363、550、800、1100 kV。"
    )

    capacitive_pref = (
        "用户录入优先；未录入按额定容性电流优选值表：I1(3.6/7.2/12/24/40.5/72.5=10A,126=31.5A,252=125A,363=315A,550=500A,800=900A,1100=1200A)，"
        "Ic(3.6/7.2=10A,12=25A,24=31.5A,40.5=50A,72.5=125A,126=140A,252=250A,363=355A,550=500A)，"
        "Isb/Ibb=400A，Ibi=20kA。"
    )
    canonical_overrides.update(
        {
            ("型式试验 > 开合性能型式试验 > 容性电流开断试验(LC1)", "试验电流A"): capacitive_pref,
            ("型式试验 > 开合性能型式试验 > 容性电流开断试验(LC2)", "试验电流A"): capacitive_pref,
            ("型式试验 > 开合性能型式试验 > 容性电流开断试验(CC1)", "试验电流A"): capacitive_pref,
            ("型式试验 > 开合性能型式试验 > 容性电流开断试验(CC2)", "试验电流A"): capacitive_pref,
            ("型式试验 > 开合性能型式试验 > 容性电流开断试验(BC1)", "试验电流A"): "用户录入优先；未录入按优选值：Isb=400A，Ibb=400A，Ibi=20kA。",
            ("型式试验 > 开合性能型式试验 > 容性电流开断试验(BC2)", "试验电流A"): "用户录入优先；未录入按优选值：Isb=400A，Ibb=400A，Ibi=20kA。",
            ("型式试验 > 开合性能型式试验 > 容性电流开断试验(BC1)", "试验类别"): "单个电容器组或背对背电容器组",
            ("型式试验 > 开合性能型式试验 > 容性电流开断试验(BC2)", "试验类别"): "单个电容器组或背对背电容器组",
            ("型式试验 > 开合性能型式试验 > 容性电流开断试验(BC1)", "操作顺序"): "O",
            ("型式试验 > 开合性能型式试验 > 容性电流开断试验(BC2)", "操作顺序"): "CO",
            ("型式试验 > 开合性能型式试验 > 容性电流开断试验(BC1)", "开合容性电流能力的级别"): "C1或C2",
            ("型式试验 > 开合性能型式试验 > 容性电流开断试验(BC2)", "开合容性电流能力的级别"): "C1或C2",
        }
    )

    for path_key, rule in (payload.get("tests_by_path", {}) or {}).items():
        if not isinstance(rule, dict):
            continue
        for param in (rule.get("parameters", []) or []):
            if not isinstance(param, dict):
                continue
            param_name = str(param.get("param_name", "") or "")
            if (
                "容性电流开断试验" in path_key
                and any(token in param_name for token in ("电缆充电开断电流", "线路充电开断电流"))
            ):
                param_name = "试验电流A"
                param["param_name"] = param_name
            if param_name == "试验次数" and "与BC2相同分布模式" in str(
                param.get("value_text", "") or ""
            ):
                normalized_count_text = "按标准规定次数执行（依据操作顺序）"
                param["value_text"] = normalized_count_text
                param["value_expr"] = normalized_count_text
                param["constraints"] = normalized_count_text
                param["value_source"] = "standard"
                param["value_type"] = "standard"
                param["derive_from_rated"] = ""
                continue
            if param_name == "试验次数" and "与BC1相同分布模式" in str(
                param.get("value_text", "") or ""
            ):
                normalized_count_text = "按标准规定次数执行（依据操作顺序）"
                param["value_text"] = normalized_count_text
                param["value_expr"] = normalized_count_text
                param["constraints"] = normalized_count_text
                param["value_source"] = "standard"
                param["value_type"] = "standard"
                param["derive_from_rated"] = ""
                continue
            if param_name == "额定电压":
                if "型式试验 > 绝缘性能型式试验 >" in path_key:
                    param["value_text"] = insulation_rated_voltage
                    param["value_expr"] = insulation_rated_voltage
                    param["constraints"] = insulation_rated_voltage
                    param["value_source"] = "standard"
                    param["value_type"] = "standard"
                    param["derive_from_rated"] = ""
                else:
                    param["value_text"] = "额定电压（用户录入）"
                    param["value_expr"] = "额定电压（用户录入）"
                    param["constraints"] = "额定电压（用户录入）"
                    param["value_source"] = "user_input"
                    param["value_type"] = "user_input"
                    param["derive_from_rated"] = "额定电压（用户录入）"
                continue
            override_value = canonical_overrides.get((path_key, param_name))
            if not override_value:
                continue
            param["value_text"] = override_value
            param["value_expr"] = override_value
            param["constraints"] = override_value
            if param_name == "试验电流A":
                param["value_source"] = "user_input"
                param["value_type"] = "user_input"
                param["derive_from_rated"] = "用户录入优先；未录入按额定容性电流优选值表。"

    for rule in (payload.get("tests_by_path", {}) or {}).values():
        if not isinstance(rule, dict):
            continue
        dedup_params = []
        seen_keys = set()
        for param in (rule.get("parameters", []) or []):
            if not isinstance(param, dict):
                continue
            if isinstance(param.get("derive_from_rated"), str) and "应当为用户录入的额定电缆充电开断电流10%-40%" in param.get("derive_from_rated", ""):
                param["derive_from_rated"] = "用户录入优先；未录入按额定容性电流优选值表。"
            key = normalize(str(param.get("param_key", "") or param.get("param_name", "")))
            if key and key in seen_keys:
                continue
            if key:
                seen_keys.add(key)
            dedup_params.append(param)
        rule["parameters"] = dedup_params

    tests_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rule in (payload.get("tests_by_path", {}) or {}).values():
        if not isinstance(rule, dict):
            continue
        name_key = normalize(str(rule.get("test_name", "") or ""))
        if name_key:
            tests_by_name[name_key].append(rule)
    payload["tests_by_name"] = dict(tests_by_name)
    return payload


def load_patch(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return extract_rules_from_tree_payload(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build cumulative annotation memory from tree/rules JSON files.")
    parser.add_argument("--output", required=True, help="Output annotation_memory.json path")
    parser.add_argument("inputs", nargs="+", help="Input tree/rules JSON files in chronological order")
    args = parser.parse_args()

    merged: dict[str, Any] = {"tests_by_path": {}, "tests_by_name": {}, "add_test_items": []}
    for raw in args.inputs:
        path = Path(raw)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            raise FileNotFoundError(f"Input not found: {path}")
        patch = load_patch(path)
        merged = merge_rules(merged, patch)
        print(f"merged: {path.name} -> tests_by_path={len(merged.get('tests_by_path', {}))}, add_test_items={len(merged.get('add_test_items', []))}")

    output = Path(args.output)
    if not output.is_absolute():
        output = Path.cwd() / output
    output.parent.mkdir(parents=True, exist_ok=True)
    merged = _sanitize_memory_payload(merged)
    output.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written: {output}")


if __name__ == "__main__":
    main()
