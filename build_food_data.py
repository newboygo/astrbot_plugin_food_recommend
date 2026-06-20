# -*- coding: utf-8 -*-
"""
一键重建 food_data.json（数据溯源工具）

数据源: Anduin2017/HowToCook (The Unlicense / 公共领域)
流程: 浅克隆 HowToCook → 解析 dishes/**/*.md → 清洗 → 输出 food_data.json → 删除临时克隆

用法:
    python build_food_data.py
"""
import os
import re
import sys
import json
import glob
import shutil
import subprocess
import tempfile

REPO = "https://github.com/Anduin2017/HowToCook.git"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "food_data.json")

CATEGORY_MAP = {
    "breakfast": "早餐", "meat_dish": "荤菜", "vegetable_dish": "素菜",
    "aquatic": "水产", "soup": "汤羹", "staple": "主食",
    "dessert": "甜品", "drink": "饮品", "condiment": "酱料",
    "semi-finished": "半成品",
}
DIFFICULTY_MAP = {
    0: "⭐ 入门", 1: "⭐ 入门", 2: "⭐⭐ 简单",
    3: "⭐⭐⭐ 中等", 4: "⭐⭐⭐⭐ 偏难", 5: "⭐⭐⭐⭐⭐ 困难",
}


def strip_md(s):
    s = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    return s.replace("**", "").replace("__", "").strip()


def clean_name(title):
    name = title.lstrip("#").strip()
    return re.sub(r"(的做法|的做法。|的简易教程|简易教程|教程|制作方法|的制法)$", "", name).strip()


def extract_difficulty(text):
    m = re.search(r"预估烹饪难度[：:]\s*(★+)", text)
    if m:
        return min(len(m.group(1)), 5)
    m = re.search(r"预估烹饪难度[：:]\s*(\d)", text)
    if m:
        return min(int(m.group(1)), 5)
    return None


def extract_time(text):
    for pat, repl in [
        (r"大约\s*([\d.]+)\s*[-~至到]\s*([\d.]+)\s*(小时|分钟)", r"\1-\2\3"),
        (r"大约\s*([\d.]+)\s*小时", r"\1小时"),
        (r"大约\s*([\d.]+)\s*分钟", r"\1分钟"),
        (r"([\d.]+)\s*[-~]\s*([\d.]+)\s*分钟", r"\1-\2分钟"),
        (r"(\d+)\s*分钟", r"\1分钟"),
    ]:
        m = re.search(pat, text)
        if m:
            return re.sub(pat, repl, m.group(0))
    return ""


def get_section(lines, keyword):
    in_sec, out = False, []
    for line in lines:
        s = line.strip()
        if s.startswith("## "):
            if in_sec:
                break
            if keyword in s:
                in_sec = True
                continue
        elif in_sec:
            out.append(line)
    return out


def parse_ingredients(lines):
    items = []
    for line in get_section(lines, "必备原料"):
        s = line.strip()
        if s.startswith(("- ", "* ")):
            item = strip_md(s[2:].strip())
            if item and len(item) < 40:
                items.append(item)
    return items


def parse_steps(lines):
    steps = []
    for raw in get_section(lines, "操作"):
        s = raw.strip()
        if not s:
            continue
        if s.startswith("### "):
            h = s[4:].strip()
            if h:
                steps.append(f"【{h}】")
            continue
        m = re.match(r"^(\d+)[.、)]\s+(.*)", s)
        if m:
            steps.append(strip_md(m.group(2)))
            continue
        if s.startswith(("- ", "* ")) and steps:
            d = strip_md(s[2:].strip())
            if d:
                steps[-1] += f"（{d}）"
    return steps


def parse_recipe(text, category, filepath):
    lines = text.splitlines()
    name, desc_lines = None, []
    for i, line in enumerate(lines):
        if line.strip().startswith("# ") and name is None:
            name = clean_name(line)
            for j in range(i + 1, len(lines)):
                ln = lines[j].strip()
                if not ln:
                    continue
                if ln.startswith("预估") or ln.startswith("##") or ln.startswith("# "):
                    break
                desc_lines.append(strip_md(ln))
            break
    if not name:
        name = os.path.splitext(os.path.basename(filepath))[0]
    desc = "".join(desc_lines).strip()
    if len(desc) > 100:
        desc = desc[:97] + "..."
    stars = extract_difficulty(text)
    difficulty = DIFFICULTY_MAP.get(stars, "⭐⭐ 简单") if stars is not None else "⭐⭐ 简单"
    return {
        "name": name,
        "category": category,
        "difficulty": difficulty,
        "time": extract_time(desc) or extract_time(text) or "未标注",
        "desc": desc or f"一道来自 HowToCook 的{category}菜谱。",
        "ingredients": "、".join(parse_ingredients(lines)),
        "steps": parse_steps(lines),
        "source": "HowToCook",
    }


def main():
    tmp = tempfile.mkdtemp(prefix="howtocook_")
    try:
        print(f"[1/3] 浅克隆 HowToCook → {tmp}")
        subprocess.check_call(
            ["git", "clone", "--depth", "1", REPO, tmp],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        src = os.path.join(tmp, "dishes")

        print("[2/3] 解析 & 清洗菜谱")
        files = glob.glob(os.path.join(src, "**", "*.md"), recursive=True)
        recipes, seen, stats, skipped = [], set(), {}, 0
        for fp in sorted(files):
            if os.sep + "template" in fp or "/template/" in fp.replace("\\", "/"):
                continue
            rel = os.path.relpath(fp, src).replace("\\", "/")
            category = CATEGORY_MAP.get(rel.split("/")[0])
            if not category:
                continue
            try:
                text = open(fp, encoding="utf-8").read()
            except Exception:
                skipped += 1
                continue
            if len(text) < 120:
                skipped += 1
                continue
            rec = parse_recipe(text, category, fp)
            if not rec["steps"] or not rec["ingredients"] or rec["name"] in seen:
                skipped += 1
                continue
            seen.add(rec["name"])
            recipes.append(rec)
            stats[category] = stats.get(category, 0) + 1

        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(recipes, f, ensure_ascii=False, indent=2)

        print(f"[3/3] 完成: {len(recipes)} 道菜 → {OUT}")
        for k in sorted(stats, key=lambda x: -stats[x]):
            print(f"  {k}: {stats[k]}")
        if skipped:
            print(f"  (跳过 {skipped} 个不完整条目)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        print("(已清理临时克隆)")


if __name__ == "__main__":
    main()
