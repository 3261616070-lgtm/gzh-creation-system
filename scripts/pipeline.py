"""润墨 → 朱雀 一条命令跑完（第 10、11 步）。

用法：python -I pipeline.py <降AI前稿.md> [-m deep3] [-t 50] [--skip-runmo]
- 降AI后稿写在降AI前稿同目录，文件名 <文章名>-降AI后.md，已存在就加 v2、v3，不覆盖。
- 润墨失败自动重试一次，仍失败换 deep 兜底一次；再失败跳过润墨，改测降AI前稿。
- 只测降AI后稿（没跑成润墨时测降AI前稿）。
- 密钥由 runmo.py / zhuque.py 自读，本脚本不接触。
退出码沿用朱雀：0 = 通过；3 = 超阈值；1 = 检测未跑成（缺密钥或接口失败）。
"""
import argparse
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = dict(os.environ, PYTHONIOENCODING='utf-8')


def run(args):
    p = subprocess.run([sys.executable, '-I'] + args, capture_output=True,
                       text=True, encoding='utf-8', errors='replace', env=ENV,
                       stdin=subprocess.DEVNULL)
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def body_len(path):
    with open(path, encoding='utf-8') as f:
        t = f.read()
    return len(re.sub(r'\s', '', t.split('\n', 1)[1] if '\n' in t else ''))


def free_name(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists('%sv%d%s' % (base, n, ext)):
        n += 1
    return '%sv%d%s' % (base, n, ext)


def runmo(src, mode):
    out = free_name(re.sub(r'-降AI前(v\d+)?\.md$', '-降AI后.md', src)
                    if src.endswith('.md') and '-降AI前' in src
                    else os.path.splitext(src)[0] + '-降AI后.md')
    tries = [mode, mode] + (['deep'] if mode != 'deep' else [])
    for i, m in enumerate(tries, 1):
        code, log = run([os.path.join(HERE, 'runmo.py'), src, '-m', m, '--body-only', '-o', out])
        rid = re.search(r'req_\w+', log)
        print('润墨第 %d 次（%s）：%s%s' % (i, m, '成功' if code == 0 else '失败',
              '，任务号 ' + rid.group(0) if rid else ''))
        if code == 0 and os.path.isfile(out):
            return out, m
        print('  ' + (log.strip().splitlines() or ['无输出'])[-1])
        if '没有提供 API Key' in log:
            break  # 缺密钥，不再重试
    return None, None


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='润墨 + 朱雀流水线')
    ap.add_argument('draft', help='降AI前稿（只含标题行和正文）')
    ap.add_argument('-m', '--mode', default='deep3')
    ap.add_argument('-t', '--threshold', default='50')
    ap.add_argument('--skip-runmo', action='store_true', help='缺润墨密钥时用，直接测降AI前稿')
    a = ap.parse_args()

    src = os.path.abspath(a.draft)
    if not os.path.isfile(src):
        print('找不到降AI前稿：%s' % src)
        return 1
    print('降AI前稿正文字数：%d' % body_len(src))

    target, mode = (None, None) if a.skip_runmo else runmo(src, a.mode)
    if target:
        print('降AI后稿：%s（正文 %d 字，模式 %s）' % (target.replace('\\', '/'), body_len(target), mode))
    else:
        target = src
        print('润墨未跑成，改测降AI前稿')

    code, log = run([os.path.join(HERE, 'zhuque.py'), target, '-t', a.threshold])
    print('---- 朱雀 ----')
    print(log.strip())
    return code


if __name__ == '__main__':
    sys.exit(main())
