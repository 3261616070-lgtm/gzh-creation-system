#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
润墨智检（Runmo）API 调用脚本 —— 零依赖，只用 Python 标准库。

把一段文字或整个文件提交给润墨处理，自动等待结果并保存。

用法示例：
    python runmo.py 文章.md                 # 用 deep3 模式处理整个文件，结果存 文章-runmo.md
    python runmo.py 文章.md -m deep         # 指定模式（2.0）
    python runmo.py 文章.md -o 输出.md      # 指定输出文件名
    python runmo.py --text "一小段文字"      # 直接处理一段文本，结果打印出来
    python runmo.py --check req_xxxx        # 查询某个任务的结果（任务没跑完也能查）
    python runmo.py 文章.md --body-only     # 首行标题原样拼回，只处理正文（工作流用这条）
    # --keep-tail（保留结尾互动钩子）已停用：结尾不写钩子，不要传这个参数

模式（-m）：
    layout             轻度排版
    quick_narrative    快速优化 · 叙事
    quick_explanatory  快速优化 · 说明
    deep               深度优化 2.0
    deep3              深度优化 3.0（默认）

API Key 的提供方式（三选一）：
    1. 环境变量：set RUNMO_API_KEY=rm_live_xxx   （推荐）
    2. 命令行：  python runmo.py 文章.md -k rm_live_xxx
    3. 都不给时，运行时提示你粘贴
"""
import argparse
import json
import os
import re
import sys
import time
import uuid
import urllib.error
import urllib.request

# Windows 控制台默认 GBK，先调成 UTF-8，避免中文乱码/报错
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

BASE = os.environ.get('RUNMO_API_BASE', 'https://www.runmo.art/api/v1')
MODES = {
    'layout': '轻度排版',
    'quick_narrative': '快速优化 · 叙事',
    'quick_explanatory': '快速优化 · 说明',
    'deep': '深度优化 2.0',
    'deep3': '深度优化 3.0',
}


def _read_keyfile(path):
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as f:
                v = f.read().strip()
            if v:
                return v
        except OSError:
            pass
    return ''


def get_key(cli_key=None):
    key = (cli_key or os.environ.get('RUNMO_API_KEY') or '').strip()
    if key:
        return key
    # 依次查找 runmo.key（一行纯文本）：脚本同目录，以及当前目录向上各级的
    # 本级目录与 工具/ 子目录。这样脚本装在 skill 里、密钥留在工作区也能读到。
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [os.path.join(here, 'runmo.key')]
    cur = os.getcwd()
    seen = set()
    for _ in range(6):
        if cur in seen:
            break
        seen.add(cur)
        candidates.append(os.path.join(cur, 'runmo.key'))
        candidates.append(os.path.join(cur, '工具', 'runmo.key'))
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    for c in candidates:
        key = _read_keyfile(c)
        if key:
            return key
    try:
        key = input('粘贴你的 Runmo API Key（rm_live_ 开头）：').strip()
    except EOFError:
        key = ''
    if not key:
        sys.exit('没有提供 API Key，退出。')
    return key


def api(method, path, key, body=None, timeout=120):
    url = BASE + path
    data = json.dumps(body, ensure_ascii=False).encode('utf-8') if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header('Authorization', 'Bearer ' + key)
    if body is not None:
        r.add_header('Content-Type', 'application/json')
    if method == 'POST':
        # 官方要求必填幂等键，每次请求都要一个新的
        r.add_header('Idempotency-Key', str(uuid.uuid4()))
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')
        sys.exit('请求失败 HTTP %s：%s' % (e.code, detail))
    except urllib.error.URLError as e:
        sys.exit('网络错误：%s' % e)


def submit(key, mode, text):
    print('提交任务（模式：%s，%s，共 %d 字）...' % (mode, MODES.get(mode, mode), len(text)))
    r = api('POST', '/rewrite', key, {'mode': mode, 'text': text})
    rid = r.get('request_id')
    print('已受理，任务号：%s（状态 %s）' % (rid, r.get('status')))
    return rid


def wait_result(key, request_id, interval=5, timeout=900):
    start = time.time()
    last = None
    while True:
        j = api('GET', '/jobs/%s' % request_id, key)
        st = j.get('status')
        if st != last or st == 'completed':
            print('  状态 %s｜进度 %s%%' % (st, j.get('progress', '?')))
            last = st
        if st == 'completed':
            return j
        if st in ('failed', 'error', 'canceled', 'cancelled'):
            sys.exit('任务失败：%s' % json.dumps(j, ensure_ascii=False))
        if time.time() - start > timeout:
            sys.exit('等待超时。任务可能还在跑，稍后用 --check %s 再查。' % request_id)
        time.sleep(interval)


# 结尾互动钩子的识别特征词
TAIL_HINTS = ('留言', '评论', '聊聊', '说说', '你会', '你觉得', '你怎么',
              '欢迎', '说说看', '看你的', '选哪个', '怎么选', '打算')


def split_tail(text, max_len=120):
    """把正文末尾的互动钩子切出来。

    返回 (body, tail)；识别不到时 tail 为空串，正文原样返回。
    判断依据：末尾段落在 max_len 字以内，且含问号或互动特征词。
    """
    blocks = re.split(r'\n\s*\n', text.rstrip())
    if len(blocks) < 2:
        return text, ''
    tail = blocks[-1].strip()
    if not tail or len(tail) > max_len:
        return text, ''
    if '？' in tail or '?' in tail or any(h in tail for h in TAIL_HINTS):
        body = '\n\n'.join(blocks[:-1]).rstrip()
        # 正文段为空、或只剩一行标题时，不能切（否则会把正文整段带走）
        if not body or body.lstrip().startswith('#'):
            return text, ''
        return body, tail
    return text, ''


def main():
    ap = argparse.ArgumentParser(description='润墨智检 API 调用脚本')
    ap.add_argument('file', nargs='?', help='要处理的文本文件（.md / .txt）')
    ap.add_argument('--text', help='直接给一段文本来处理')
    ap.add_argument('--check', metavar='REQUEST_ID', help='查询某个任务的结果')
    ap.add_argument('-m', '--mode', default='deep3', choices=sorted(MODES),
                    help='处理模式，默认 deep3')
    ap.add_argument('-o', '--output', help='结果输出文件；不给时文件模式存为 原名-runmo.md，文本模式直接打印')
    ap.add_argument('-k', '--key', help='API Key（不填则读环境变量 RUNMO_API_KEY）')
    ap.add_argument('--body-only', action='store_true',
                    help='文件首行是「# 标题」时不处理它（只改造正文），输出时自动把标题原样拼回')
    ap.add_argument('--keep-tail', action='store_true',
                    help='正文末尾的互动钩子不参与处理，输出时原样拼回（宁可少改，也不动结尾）')
    args = ap.parse_args()

    key = get_key(args.key)

    # --- 查询模式 ---
    if args.check:
        j = api('GET', '/jobs/%s' % args.check, key)
        print(json.dumps(j, ensure_ascii=False, indent=2))
        return

    # --- 取输入文本 ---
    head = ''
    if args.text:
        text = args.text
        default_out = None
    elif args.file:
        if not os.path.isfile(args.file):
            sys.exit('找不到文件：%s' % args.file)
        with open(args.file, encoding='utf-8') as f:
            text = f.read()
        if args.body_only:
            first, _, rest = text.partition('\n')
            if first.lstrip().startswith('#'):
                head = first + '\n\n'
                text = rest.lstrip('\n')
        base, ext = os.path.splitext(args.file)
        default_out = base + '-runmo' + (ext or '.md')
    else:
        ap.print_help()
        sys.exit(1)

    # --- 结尾互动钩子保护 ---
    tail = ''
    if args.keep_tail:
        text, tail = split_tail(text)
        if not tail:
            print('提示：没识别到结尾互动钩子，本次未做尾部保护。')

    # --- 提交并等待 ---
    rid = submit(key, args.mode, text)
    j = wait_result(key, rid)
    result = j.get('text', '')

    if head:
        result = head + result
    if tail:
        result = result.rstrip() + '\n\n' + tail + '\n'

    out = args.output or default_out
    if out:
        with open(out, 'w', encoding='utf-8') as f:
            f.write(result)
        print('\n完成。结果已保存到：%s（%d 字）' % (out, len(result)))
    else:
        print('\n===== 处理结果 =====')
        print(result)


if __name__ == '__main__':
    main()
