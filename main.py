import os
import json
import random
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

# 菜谱数据文件（与 main.py 同目录）
DATA_PATH = os.path.join(os.path.dirname(__file__), "food_data.json")

# HowToCook 原生分类（按目录组织）
ALL_CATEGORIES = [
    "早餐", "荤菜", "素菜", "水产", "汤羹",
    "主食", "甜品", "饮品", "酱料", "半成品",
]

# 口语"餐类"词 → 实际菜谱分类（兼容用户说 早/午/晚/夜宵 的习惯）
MEAL_TO_CATEGORIES = {
    "早餐": ["早餐"], "早点": ["早餐"], "早饭": ["早餐"],
    "午餐": ["荤菜", "素菜", "水产", "汤羹"],
    "午饭": ["荤菜", "素菜", "水产", "汤羹"],
    "正餐": ["荤菜", "素菜", "水产", "汤羹"],
    "晚餐": ["荤菜", "素菜", "水产", "汤羹"],
    "晚饭": ["荤菜", "素菜", "水产", "汤羹"],
    "夜宵": ["主食", "荤菜", "汤羹"],
    "宵夜": ["主食", "荤菜", "汤羹"],
}

# 分类名别名 → 标准分类
CATEGORY_ALIAS = {
    "早餐": "早餐", "荤菜": "荤菜", "肉菜": "荤菜", "肉": "荤菜",
    "素菜": "素菜", "蔬菜": "素菜", "青菜": "素菜",
    "水产": "水产", "海鲜": "水产", "鱼": "水产",
    "汤": "汤羹", "汤羹": "汤羹", "煲汤": "汤羹",
    "主食": "主食", "面食": "主食",
    "甜品": "甜品", "甜点": "甜品", "甜食": "甜品",
    "饮品": "饮品", "饮料": "饮品", "喝的": "饮品",
    "酱料": "酱料", "调料": "酱料",
    "半成品": "半成品",
}

# 自然语言触发关键词
TRIGGER_KEYWORDS = [
    "吃什么", "吃啥", "吃点啥", "推荐点吃的", "不知道吃什么",
    "今天吃什么", "想吃啥", "推荐美食", "推荐食物", "美食推荐",
]


def load_food_db():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


class FoodRecommendPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        try:
            self.food_db = load_food_db()
            logger.info(f"美食推荐插件已加载，共收录 {len(self.food_db)} 道菜")
        except Exception as e:
            logger.error(f"美食推荐插件数据加载失败: {e}")
            self.food_db = []

    # ========== 工具：从文本解析要筛选的分类 ==========
    def _resolve_categories(self, text):
        """返回 (categories_list, label) 或 None"""
        text = (text or "").strip()
        if not text:
            return None
        # 1. 口语餐类词（早/午/晚/夜宵）
        for meal, cats in MEAL_TO_CATEGORIES.items():
            if meal in text:
                return cats, meal
        # 2. 分类名 / 别名
        for kw, cat in CATEGORY_ALIAS.items():
            if kw in text:
                return [cat], cat
        return None

    def _pick_from(self, foods):
        return random.choice(foods) if foods else None

    # ========== 指令：吃什么 ==========
    @filter.command("吃什么", alias={"吃啥", "food", "今天吃什么", "推荐食物"})
    async def recommend(self, event: AstrMessageEvent, message: str = ""):
        """随机推荐食物，可选参数：早餐/午餐/晚餐/夜宵 或 荤菜/素菜/汤/主食..."""
        if not self.food_db:
            yield event.plain_result("菜谱数据加载失败，请检查 food_data.json")
            event.stop_event()
            return

        resolved = self._resolve_categories(message)
        if resolved:
            cats, label = resolved
            foods = [f for f in self.food_db if f["category"] in cats]
        else:
            foods = self.food_db
            label = "随机"

        if not foods:
            yield event.plain_result("没有找到该分类的食物，试试「/吃什么」获取随机推荐吧~")
            event.stop_event()
            return

        picked = self._pick_from(foods)
        yield event.plain_result(self._format_food_card(picked, label))
        event.stop_event()

    # ========== 指令：怎么做 ==========
    @filter.command("怎么做", alias={"howto", "食谱", "做法", "recipe"})
    async def howto(self, event: AstrMessageEvent, message: str = ""):
        """查询指定菜品的详细做法"""
        dish = (message or "").strip()
        if not dish:
            yield event.plain_result(
                "请告诉我想要查询的菜名哦~ 例如：\n/怎么做 宫保鸡丁\n\n"
                "发送 /吃什么 可以随机推荐美食！"
            )
            event.stop_event()
            return

        # 精确匹配优先，模糊匹配兜底
        matched = next((f for f in self.food_db if dish == f["name"]), None)
        if not matched:
            matched = next(
                (f for f in self.food_db if dish in f["name"] or f["name"] in dish),
                None,
            )

        if not matched:
            yield event.plain_result(
                f"抱歉，还没有收录「{dish}」的做法~ 😅\n"
                "发送 /吃什么 获取随机推荐吧！"
            )
            event.stop_event()
            return

        yield event.plain_result(self._format_food_card(matched))
        event.stop_event()

    # ========== 指令：菜单 ==========
    @filter.command("菜单", alias={"menu", "全部菜谱", "美食列表"})
    async def menu(self, event: AstrMessageEvent):
        """按分类列出所有菜品"""
        if not self.food_db:
            yield event.plain_result("菜谱数据加载失败，请检查 food_data.json")
            event.stop_event()
            return

        groups = {}
        for f in self.food_db:
            groups.setdefault(f["category"], []).append(f["name"])

        lines = [f"📋 已收录菜品清单（共 {len(self.food_db)} 道）\n"]
        for cat in ALL_CATEGORIES:
            names = groups.get(cat, [])
            if not names:
                continue
            lines.append(f"【{cat}】({len(names)}道)")
            preview = "、".join(names[:25])
            if len(names) > 25:
                preview += f" ……等{len(names)}道"
            lines.append(f"  {preview}")

        lines.append("\n发送 /吃什么 随机推荐")
        lines.append("发送 /吃什么 早餐/午餐/荤菜/汤… 按类推荐")
        lines.append("发送 /怎么做 <菜名> 查看做法")

        yield event.plain_result("\n".join(lines))
        event.stop_event()

    # ========== 自然语言触发 ==========
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """监听包含关键词的自然语言消息"""
        # 被唤醒词/命令触发的消息交给指令处理器，避免重复响应
        if event.is_at_or_wake_command:
            return

        msg = event.get_message_str()
        if not msg:
            return

        if not any(kw in msg for kw in TRIGGER_KEYWORDS):
            return

        # 解析餐类/分类
        resolved = self._resolve_categories(msg)
        if resolved:
            cats, label = resolved
            foods = [f for f in self.food_db if f["category"] in cats]
            if foods:
                yield event.plain_result(
                    self._format_food_card(self._pick_from(foods), label)
                )
                event.stop_event()
                return

        # 随机推荐
        if self.food_db:
            yield event.plain_result(
                self._format_food_card(self._pick_from(self.food_db), "随机")
            )
            event.stop_event()

    # ========== 格式化输出 ==========
    def _format_food_card(self, food: dict, category_label: str = "") -> str:
        """将食物信息格式化为美观的文本卡片"""
        emoji_map = {
            "早餐": "🌅", "荤菜": "🍖", "素菜": "🥬", "水产": "🐟",
            "汤羹": "🍲", "主食": "🍚", "甜品": "🍰", "饮品": "🥤",
            "酱料": "🧂", "半成品": "📦", "随机": "🎲",
        }
        cat = food.get("category", "")
        emoji = emoji_map.get(cat, "🍽️")
        steps = food.get("steps") or []

        lines = [
            f"{emoji} {food.get('name', '未知菜品')}",
            f"📂 分类：{cat or '未知'}",
            f"⏱️ 耗时：{food.get('time', '未标注')}",
            f"📊 难度：{food.get('difficulty', '未知')}",
            "",
            f"💬 {food.get('desc', '')}",
            "",
            f"📝 食材：{food.get('ingredients', '见原菜谱')}",
            "",
            "👨‍🍳 做法步骤：",
        ]
        for i, step in enumerate(steps, 1):
            lines.append(f"  {i}. {step}")

        lines.append("")
        lines.append("🍜 祝你用餐愉快！")
        return "\n".join(lines)

    async def terminate(self):
        """插件卸载时调用"""
        logger.info("美食推荐插件已卸载。")
