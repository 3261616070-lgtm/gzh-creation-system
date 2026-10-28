#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
朱雀 AI 检测（腾讯 EdgeOne Makers）调用脚本 —— 零依赖，只用 Python 标准库。

把发布稿交给朱雀文本检测，打印 AI 率与判定，不改动原文件。

用法示例：
    python zhuque.py 发布稿.md                  # 检测整篇，阈值默认 50%
    python zhuque.py 发布稿.md -t 30            # 自定义阈值（百分比）
    python zhuque.py --text "一小段文字"        # 直接检测一段文本

API Key 的提供方式（优先级从高到低）：
    1. 命令行：  -k sk-xxx
    2. 环境变量：ZHUQUE_API_KEY
    3. 工作区文件：工具/zhuque.key（一行纯文本）

退出码：0 未超阈值；3 超阈值；1 调用失败或缺密钥。
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

URL = os.environ.get(
    'ZHUQUE_API_URL',
    'https://ai-gateway.edgeone.link/v1/providers/zhuque-text/classify')
LABELS = {0: '人工', 1: 'AI', 2: '疑似AI'}


def _read_keyfile(path):
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as f:
                v = f.read().strip()
            if v:
                return v
        except Exception:
            pass
    return None


def get_key(cli_key, start_dir=None):
    if cli_key:
        return cli_key
    v = os.environ.get('ZHUQUE_API_KEY', '').strip()
    if v:
        return v
    # 依次查找 zhuque.key：脚本同目录，以及待测文件所在目录、当前目录向上各级的
    # 本级目录与 工具/ 子目录。这样从任意目录调用都能读到工作区里的密钥。
    starts = [d for d in (start_dir, os.getcwd()) if d]
    cands = [os.path.join(os.path.dirname(os.path.abspath(__file__)), 'zhuque.key')]
    for cur in starts:
        for _ in range(6):
            cands += [os.path.join(cur, '工具', 'zhuque.key'),
                      os.path.join(cur, 'zhuque.key')]
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    for p in cands:
        v = _read_keyfile(p)
        if v:
            return v
    return None


def clean(text):
    """去掉 Markdown 标记，只留读者看到的文字。"""
    text = text.replace('\r\n', '\n')
    text = re.sub(r'^---\n.*?\n---\n', '', text, flags=re.S)  # frontmatter
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.M)
    text = text.replace('**', '')
    text = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', text)
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def classify(text, key):
    req = urllib.request.Request(
        URL,
        data=json.dumps({'text': text}).encode('utf-8'),
        headers={'Authorization': 'Bearer ' + key,
                 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def main():
    ap = argparse.ArgumentParser(description='朱雀 AI 检测')
    ap.add_argument('file', nargs='?', help='要检测的 Markdown 文件')
    ap.add_argument('--text', help='直接检测一段文本')
    ap.add_argument('-t', '--threshold', type=float, default=50,
                    help='AI 率阈值（百分比，默认 50）')
    ap.add_argument('-k', '--key', help='API Key（不推荐在命令行传）')
    a = ap.parse_args()

    if a.text:
        text = a.text
    elif a.file:
        with open(a.file, encoding='utf-8') as f:
            text = clean(f.read())
    else:
        ap.error('需要文件路径或 --text')

    key = get_key(a.key, os.path.dirname(os.path.abspath(a.file)) if a.file else None)
    if not key:
        print('缺少朱雀密钥（工具/zhuque.key 或 ZHUQUE_API_KEY），跳过检测。')
        return 1

    try:
        r = classify(text, key)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')[:300]
        print(f'朱雀接口报错 HTTP {e.code}：{body}')
        return 1
    except Exception as e:
        print(f'朱雀接口调用失败：{e}')
        return 1

    if r.get('status') != 'success':
        print(f'朱雀检测未成功：{r.get("msg") or r.get("status")}')
        return 1

    lr = {str(k): v for k, v in (r.get('labels_ratio') or {}).items()}
    ai = float(lr.get('1', 0))
    sus = float(lr.get('2', 0))
    human = float(lr.get('0', 0))
    rate = (ai + sus) * 100
    over = rate >= a.threshold

    print(f'字数：{len(text)}')
    print(f'AI率：{rate:.1f}%（AI {ai*100:.1f}% / 疑似AI {sus*100:.1f}% / 人工 {human*100:.1f}%）')
    print(f'整体风险分：{float(r.get("softmax_confidence", 0)):.4f}')
    print(f'判定：{"超阈值" if over else "通过"}（阈值 {a.threshold:g}%）')
    for s in r.get('segment_labels') or []:
        lab = s.get('label')
        if lab in (1, 2):
            frag = re.sub(r'\s+', ' ', s.get('text', ''))[:40]
            print(f'  [{LABELS.get(lab)} {float(s.get("conf", 0)):.2f}] {frag}…')
    used = (r.get('makers_models_usage') or {}).get('total_tokens')
    if used is not None:
        print(f'扣减额度：{used} token')
    return 3 if over else 0


if __name__ == '__main__':
    sys.exit(main())
