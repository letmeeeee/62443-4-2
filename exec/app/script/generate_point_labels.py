#!/usr/bin/env python3
"""从当前工作区 Python 定义和 XLSX 点表生成前端名称字典（仅使用标准库）。"""

import argparse
import ast
from collections import defaultdict
import csv
import json
import operator
from pathlib import Path
import posixpath
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul}


def literal(node, names=None):
    """只计算常量和简单算术，绝不导入或执行项目代码。"""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name) and names and node.id in names:
        return names[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -literal(node.operand, names)
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        return OPS[type(node.op)](literal(node.left, names), literal(node.right, names))
    raise ValueError(ast.dump(node))


def clean(value):
    return re.sub(r"[\u200b-\u200d\ufeff]", "", str(value)).strip()


def read_workbook(path):
    with ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = [
                "".join(t.text or "" for t in item.findall(".//m:t", NS))
                for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("m:si", NS)
            ]
        relationships = {
            r.attrib["Id"]: r.attrib["Target"]
            for r in ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        }
        sheets = ET.fromstring(archive.read("xl/workbook.xml")).findall("m:sheets/m:sheet", NS)
        result = {}
        for sheet in sheets:
            relation = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
            target = relationships[relation]
            target = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
            rows = []
            for row in ET.fromstring(archive.read(target)).findall("m:sheetData/m:row", NS):
                cells = {}
                for cell in row.findall("m:c", NS):
                    col = re.sub(r"\d", "", cell.attrib["r"])
                    value = cell.findtext("m:v", "", NS)
                    if cell.get("t") == "s":
                        value = strings[int(value)] if value else ""
                    elif cell.get("t") == "inlineStr":
                        value = "".join(t.text or "" for t in cell.findall(".//m:t", NS))
                    cells[col] = clean(value)
                rows.append((int(row.attrib["r"]), cells))
            result[sheet.attrib["name"]] = rows
        return result


def address_start(value, instance=1):
    """取首寄存器；多字寄存器只使用首地址，不扩展预留地址段。"""
    expression = (value.splitlines() or [""])[0].strip()
    if not expression or not re.fullmatch(r"[\dn+*()\s-]+", expression):
        raise ValueError(value)
    return literal(ast.parse(expression, mode="eval").body, {"n": instance})


def point_index(workbook):
    index = defaultdict(list)
    for sheet, rows in workbook.items():
        if not any(c.get("D") == "Addr(地址)" for _, c in rows):
            continue
        for row, cells in rows:
            try:
                address_start(cells.get("D", ""))
            except (ValueError, SyntaxError, TypeError):
                continue
            point = {
                "zh": cells.get("C") or None, "en": cells.get("B") or None,
                "sheet": sheet, "row": row, "address": cells["D"],
                "description_en": cells.get("E", ""),
                "description_zh": cells.get("F", ""),
            }
            # 点表明确给出 PCS 最多 4 台、Bank 最多 8 堆。
            count = 4 if sheet.startswith("PCS System") else 8 if sheet.startswith("Battery System") else 1
            instances = range(1, count + 1) if "n" in cells["D"] else (1,)
            for instance in instances:
                actual_address = address_start(cells["D"], instance)
                index[actual_address].append({**point, "instance": instance})
    return index


def bit_index(workbook):
    """状态/报警分表横向排列多组 Name/名称，以分组标题和 bit 索引。"""
    result = defaultdict(list)
    for sheet, rows in workbook.items():
        if "Status&Alarm" not in sheet:
            continue
        groups = {}
        for row, cells in rows:
            columns = sorted(cells, key=lambda col: (len(col), col))
            for i, col in enumerate(columns[:-2]):
                en_col, zh_col = columns[i + 1:i + 3]
                if cells[en_col] == "Name" and cells[zh_col] == "名称":
                    groups[col] = (cells[col], en_col, zh_col)
            for col, (title, en_col, zh_col) in groups.items():
                match = re.fullmatch(r"(?:bit)?(\d+)", cells.get(col, ""), re.I)
                if match:
                    result[(sheet, title, int(match[1]))].append({
                        "zh": re.sub(r"^bit\d+[:：]\s*", "", cells.get(zh_col, "")) or None,
                        "en": re.sub(r"^bit\d+[:：]\s*", "", cells.get(en_col, "")) or None,
                        "sheet": sheet, "row": row, "section": title,
                    })
    return result


def extract_definitions(root):
    definitions, skipped, files = [], [], []
    for path in sorted(root.rglob("*.py")):
        if any(part.startswith(".") or part in {"__pycache__", "venv", "node_modules"} for part in path.relative_to(root).parts):
            continue
        files.append(str(path.relative_to(root)))
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        names = {}
        for statement in tree.body:
            if isinstance(statement, ast.Assign):
                try:
                    value = literal(statement.value, names)
                except (ValueError, TypeError):
                    continue
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        names[target.id] = value
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            fields = {key.value: value for key, value in zip(node.keys, node.values) if isinstance(key, ast.Constant)}
            if not {"name", "address"} <= fields.keys():
                continue
            item = {"source": f"{path.relative_to(root)}:{node.lineno}"}
            try:
                for key in ("name", "address", "bitMapping", "eValue"):
                    if key in fields:
                        item[key] = literal(fields[key], names)
                if not isinstance(item["name"], str) or not isinstance(item["address"], int):
                    raise ValueError("name/address 类型不是静态字符串/整数")
            except (ValueError, TypeError) as exc:
                skipped.append({**item, "reason": str(exc)})
                continue
            if item["address"] > 60000:
                continue
            definitions.append(item)
    return definitions, skipped, files


def normalize(value):
    return re.sub(r"[\s()（）,，]+", "", value).lower()


def match_point(item, index, bits):
    candidates = index.get(item["address"], [])
    # 用户确认：12261 的模式字段与 bit0 使能按钮共用寄存器，名称分别处理。
    if item["address"] == 12261 and item["name"] == "device.pcs.ReactivePowerMode":
        return [{
            "zh": "无功模式", "en": "ReactivePowerMode",
            "address": 12261, "label_source": "user_override",
        }]
    bit = item.get("bitMapping", "")
    if bit != "":
        matches = []
        for point in candidates:
            prefix = re.sub(r"\s+System$", "", point["sheet"].split("(")[0].strip())
            for (sheet, title, number), values in bits.items():
                # 状态字标题可附带说明，例如 Status Word 6(PCS Version Verification)。
                if (sheet.startswith(prefix + " Status&Alarm") and str(number) == str(bit)
                        and normalize(title.split("(")[0]) == normalize(point["en"].split("(")[0])):
                    matches.extend(values)
        return matches
    return candidates


def nest_labels(labels):
    """按 name 的点号分层；路径冲突必须报错，避免覆盖现有翻译。"""
    result = {}
    paths = set(labels)
    for name, value in labels.items():
        parts = name.split(".")
        for depth in range(1, len(parts)):
            prefix = ".".join(parts[:depth])
            if prefix in paths:
                raise ValueError("名称路径冲突: {} / {}".format(prefix, name))
        current = result
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value
    return result


def generate(root, workbook_path, output):
    workbook = read_workbook(workbook_path)
    index, bits = point_index(workbook), bit_index(workbook)
    definitions, skipped, files = extract_definitions(root)
    grouped = defaultdict(list)
    for item in definitions:
        grouped[item["name"]].append(item)
    labels, details, issues = {}, {}, []
    for name, items in sorted(grouped.items()):
        occurrences = []
        all_labels = set()
        incomplete = False
        for item in items:
            candidates = match_point(item, index, bits)
            pairs = {(p["zh"], p["en"]) for p in candidates}
            all_labels.update(pairs)
            incomplete |= not pairs
            occurrences.append({**item, "candidates": candidates})
        # 同名多处定义只有全部匹配且名称一致时才输出，避免静默覆盖。
        if len(all_labels) == 1 and not incomplete:
            zh, en = next(iter(all_labels))
            if zh and en and zh not in {"保留", "预留"} and en.lower() != "reserved":
                labels[name] = {"zh": zh, "en": en}
                status = "matched"
            else:
                status = "reserved_or_missing_label"
        else:
            status = "unmatched" if not all_labels else "conflict" if len(all_labels) > 1 else "partially_matched"
        details[name] = {"status": status, "occurrences": occurrences}
        if status != "matched":
            labels[name] = {"zh": None, "en": None}
            issues.append({"name": name, **details[name]})
    output.mkdir(parents=True, exist_ok=True)
    stats = {
        "python_files_scanned": len(files), "definitions": len(definitions),
        "unique_names": len(grouped), "matched_names": len(grouped) - len(issues),
        "review_names": len(issues), "dynamic_definitions_skipped": len(skipped),
    }
    for filename, data in (
        ("point_labels.json", nest_labels(labels)),
        ("zh.json", nest_labels({name: label["zh"] for name, label in labels.items()})),
        ("en.json", nest_labels({name: label["en"] for name, label in labels.items()})),
        ("point_labels_report.json", {
            "workbook": posixpath.relpath(str(workbook_path), str(root)),
            "summary": stats, "scanned_files": files, "issues": issues,
            "skipped": skipped, "details": details,
        }),
    ):
        (output / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (output / "point_labels.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["name", "中文", "英文", "状态", "address", "Python来源"])
        for name, label in labels.items():
            occurrences = details[name]["occurrences"]
            writer.writerow([
                name, label["zh"], label["en"], details[name]["status"],
                ";".join(str(address) for address in sorted({p["address"] for p in occurrences})),
                ";".join(p["source"] for p in occurrences),
            ])
    print(json.dumps(stats, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, default=ROOT / "docs/设备点表.xlsx")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/i18n")
    args = parser.parse_args()
    generate(ROOT, args.workbook.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
