"""交接检查：正文里不许有核查过程、评论区内容，结尾不许留互动钩子。

用法：python check_handoff.py <改稿.md>
退出码 0 = 通过；1 = 有问题，按提示改完再跑，直到 0。
只查 frontmatter 之后的正文，标题行不查。
"""
import re
import sys

# (正则, 问题说明)
LEAK = [
    (r"(我们|我|小编|笔者)[^。！？\n]{0,12}(查|搜|翻|核|找)", "在讲「我们查了什么」"),
    (r"查不到|没查到|没能查到|搜不到|翻查|翻不到|没找到", "在讲检索结果"),
    (r"核准|无法核实|没法核实|核实不了|未经核实|暂未核实|无法确认|没法确认", "在讲核实结论"),
    (r"对不上", "在讲数字比对"),
    (r"(自己|先|去|再)[^。！？\n]{0,8}(核实|核对|查一下|看一眼)", "在让读者替我们核实"),
    (r"出处|信源|单一来源|写作依据|素材|检索|搜索结果", "用了核查用语"),
]
COMMENT = [
    (r"首评|作者赞过|条回复|写留言|已无更多数据|往期推荐|回复 ?\S+[:：]", "混进了评论区或往期推荐"),
]
# 结尾互动钩子：问句或留言召唤
HOOK = r"[？?]|留言|评论区?|聊聊|说说|你怎么看|你们怎么看|欢迎(留言|讨论|分享|交流)|你会(选|买)|你(打算|准备)"


def body_lines(text):
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    return [(i + 1, l) for i, l in enumerate(lines) if i >= start and not l.startswith("#")]


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        print("用法：python check_handoff.py <改稿.md>")
        return 2
    text = open(sys.argv[1], encoding="utf-8").read()
    body = body_lines(text)
    problems = []
    for no, line in body:
        for pat, why in LEAK + COMMENT:
            m = re.search(pat, line)
            if m:
                s = max(0, m.start() - 15)
                problems.append(f"第 {no} 行 [{why}] …{line[s:m.end() + 15]}…")
    paras = [l.strip() for _, l in body if l.strip()]
    if paras and re.search(HOOK, paras[-1]):
        problems.append(f"结尾 [留了互动钩子] …{paras[-1][-40:]}… 结尾不许有问句或留言召唤，删掉这句，在上一条信息或判断处收住")

    if not problems:
        print("交接检查通过")
        return 0
    print(f"交接检查不通过，共 {len(problems)} 处：")
    for p in problems:
        print("  " + p)
    print(
        "\n怎么改：核查过程整句删掉，或改成句内归属（「据 MacRumors」「美版标价 79 美元」）。"
        "\n不要解释这条是不是误报，换个说法重写，改完重跑，直到通过。"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
