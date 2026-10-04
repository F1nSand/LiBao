"""Render the thesis diagrams from a small, deterministic drawing script.

The figures describe only interfaces and behavior already present in the LiBao
source tree. They are generated locally so the same images can be regenerated
without an external design or image service.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


HERE = Path(__file__).resolve().parent
FONT_PATH = Path(r"C:\Windows\Fonts\msyh.ttc")
if not FONT_PATH.exists():
    FONT_PATH = Path(r"C:\Windows\Fonts\simhei.ttf")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    if bold:
        bold_path = Path(r"C:\Windows\Fonts\msyhbd.ttc")
        if bold_path.exists():
            return ImageFont.truetype(str(bold_path), size)
    return ImageFont.truetype(str(FONT_PATH), size)


def centered_text(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, fnt: ImageFont.FreeTypeFont) -> None:
    x1, y1, x2, y2 = box
    lines = text.split("\n")
    heights = [draw.textbbox((0, 0), line, font=fnt)[3] for line in lines]
    line_height = fnt.size + 8
    total = line_height * len(lines)
    y = y1 + (y2 - y1 - total) / 2
    for line, height in zip(lines, heights, strict=True):
        width = draw.textbbox((0, 0), line, font=fnt)[2]
        draw.text((x1 + (x2 - x1 - width) / 2, y), line, font=fnt, fill="#263238")
        y += line_height


def box(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], text: str, fill: str, bold: bool = False) -> None:
    draw.rounded_rectangle(rect, radius=22, fill=fill, outline="#3b4a5a", width=3)
    centered_text(draw, rect, text, font(28 if "\n" in text else 30, bold=bold))


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], label: str = "") -> None:
    draw.line((*start, *end), fill="#546e7a", width=5)
    x1, y1 = end
    x0, y0 = start
    if abs(x1 - x0) >= abs(y1 - y0):
        sign = 1 if x1 >= x0 else -1
        points = [(x1, y1), (x1 - sign * 20, y1 - 12), (x1 - sign * 20, y1 + 12)]
        lx, ly = (x0 + x1) // 2, y1 - 38
    else:
        sign = 1 if y1 >= y0 else -1
        points = [(x1, y1), (x1 - 12, y1 - sign * 20), (x1 + 12, y1 - sign * 20)]
        lx, ly = x1 + 12, (y0 + y1) // 2
    draw.polygon(points, fill="#546e7a")
    if label:
        draw.text((lx, ly), label, font=font(22), fill="#455a64")


def architecture() -> None:
    image = Image.new("RGB", (1800, 1250), "white")
    draw = ImageDraw.Draw(image)
    title = "图 3-1  LiBao 总体架构"
    draw.text((70, 38), title, font=font(38, bold=True), fill="#263238")
    box(draw, (120, 130, 830, 260), "开发环境\n浏览器 :5173 → Vite /api 代理", "#eef4f8")
    box(draw, (970, 130, 1680, 260), "发布环境\n浏览器 :8000 → FastAPI REST/SSE + SPA", "#e6f4ea")
    box(draw, (300, 340, 1500, 465), "FastAPI API 层\nREST / SSE / 统一错误信封", "#eef4f8", True)
    box(draw, (300, 535, 1500, 680), "LangGraph 编排层\nroute · memory_inject · agent_execute · tool_execute · finalize", "#fff4d6")
    box(draw, (300, 750, 1500, 895), "业务服务层\n会话 · 任务 · 工具 · MCP · 记忆 · 知识库 · 附件 · 工作区", "#eef4f8")
    box(draw, (300, 965, 1500, 1110), "本地存储与能力层\nTool Registry / 沙箱 / FileStore / JSONL / LanceDB-BM25 / checkpoints / workspaces", "#f6e6f7")
    arrow(draw, (475, 260), (600, 340), "开发请求")
    arrow(draw, (1325, 260), (1200, 340), "发布请求")
    arrow(draw, (900, 465), (900, 535))
    arrow(draw, (900, 680), (900, 750))
    arrow(draw, (900, 895), (900, 965))
    image.save(HERE / "architecture.png", dpi=(180, 180))


def task_state() -> None:
    image = Image.new("RGB", (1900, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.text((70, 38), "图 4-1  LiBao 任务状态转换", font=font(38, bold=True), fill="#263238")
    boxes = {
        "pending": (90, 360, 350, 490),
        "running": (490, 360, 750, 490),
        "waiting": (890, 150, 1250, 280),
        "done": (890, 360, 1150, 490),
        "failed": (890, 570, 1150, 700),
        "cancelled": (1330, 360, 1650, 490),
    }
    fills = {"pending": "#eef4f8", "running": "#fff4d6", "waiting": "#fff4d6", "done": "#e6f4ea", "failed": "#fce8e6", "cancelled": "#fce8e6"}
    for name, rect in boxes.items():
        box(draw, rect, name, fills[name], name in {"running", "waiting"})
    arrow(draw, (350, 425), (490, 425), "后台确认")
    arrow(draw, (750, 385), (890, 215), "工具/节点中断")
    arrow(draw, (750, 425), (890, 425), "finalize")
    arrow(draw, (750, 465), (890, 635), "结构化错误")
    arrow(draw, (1250, 215), (1040, 360), "approved")
    arrow(draw, (1250, 245), (1490, 360), "denied")
    arrow(draw, (1150, 635), (620, 490), "recover + checkpoint")
    arrow(draw, (1150, 425), (1330, 425), "用户取消")
    image.save(HERE / "task-state.png", dpi=(180, 180))


def sse_recovery() -> None:
    image = Image.new("RGB", (2200, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.text((70, 38), "图 4-2  任务事件、SSE 回放与恢复", font=font(38, bold=True), fill="#263238")
    rects = [
        (70, 350, 370, 500, "提交任务\n写入 pending", "#eef4f8"),
        (490, 350, 800, 500, "后台执行\n模型/工具/检查点", "#fff4d6"),
        (920, 350, 1280, 500, "业务事件\ntask_seq + JSONL\n再 live-tail", "#f6e6f7"),
        (1400, 350, 1740, 500, "前端 SSE\n连接 seq\n时间线更新", "#eef4f8"),
        (1860, 150, 2160, 300, "断线/刷新", "#fce8e6"),
        (1860, 600, 2160, 780, "重连\nafter_seq / Last-Event-ID\n补发并去重", "#e6f4ea"),
    ]
    for x1, y1, x2, y2, label, fill in rects:
        box(draw, (x1, y1, x2, y2), label, fill)
    arrow(draw, (370, 425), (490, 425))
    arrow(draw, (800, 425), (920, 425))
    arrow(draw, (1280, 425), (1400, 425))
    arrow(draw, (1740, 390), (1860, 225), "断开")
    arrow(draw, (2010, 300), (2010, 600), "游标")
    arrow(draw, (1860, 690), (1570, 500), "继续观察")
    arrow(draw, (800, 350), (1080, 350), "模型传输失败")
    draw.text((970, 210), "recover + checkpoint\n不重提原消息", font=font(24), fill="#455a64")
    arrow(draw, (1080, 210), (1080, 350))
    image.save(HERE / "sse-recovery.png", dpi=(180, 180))


if __name__ == "__main__":
    architecture()
    task_state()
    sse_recovery()
    print("rendered architecture.png, task-state.png, sse-recovery.png")

