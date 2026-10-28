"""依赖自检 + 建当天成品目录。一条命令替代第 1 步的逐项检查。

用法（在工作区根目录跑）：python -I preflight.py [--date YYYY-MM-DD]
输出每项 OK / 缺失，最后一行给出当天成品目录。只报密钥在否，不打印密钥。
退出码：0 = human-writing 可用（润墨/朱雀缺失只影响对应步骤）；1 = human-writing 不可用。
"""
import argparse
import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(os.path.dirname(HERE))


def key_present(name, env):
    if os.environ.get(env, '').strip():
        return '环境变量'
    cands = [os.path.join(HERE, name)]
    cur = os.getcwd()
    for _ in range(6):
        cands += [os.path.join(cur, name), os.path.join(cur, '工具', name)]
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    for c in cands:
        try:
            with open(c, encoding='utf-8') as f:
                if f.read().strip():
                    return '密钥文件'
        except OSError:
            pass
    return ''


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser(description='公众号创作系统依赖自检')
    ap.add_argument('--date', default=datetime.date.today().isoformat())
    a = ap.parse_args()

    ok = True
    hw = os.path.join(SKILLS, 'human-writing')
    prose = os.path.join(hw, 'scripts', 'check_prose.py')
    if os.path.isfile(os.path.join(hw, 'SKILL.md')):
        print('human-writing SKILL.md：OK')
    else:
        print('human-writing SKILL.md：缺失'); ok = False
    try:
        with open(prose, encoding='utf-8') as f:
            compile(f.read(), prose, 'exec')
        print('check_prose.py：OK（%s）' % prose.replace('\\', '/'))
    except Exception as e:
        print('check_prose.py：不可用（%s），第 7 步改人工检查' % e.__class__.__name__); ok = False

    for script, keyfile, env, step in (('runmo.py', 'runmo.key', 'RUNMO_API_KEY', '润墨'),
                                       ('zhuque.py', 'zhuque.key', 'ZHUQUE_API_KEY', '朱雀')):
        has_script = os.path.isfile(os.path.join(HERE, script))
        src = key_present(keyfile, env)
        if has_script and src:
            print('%s：OK（密钥来自%s）' % (step, src))
        else:
            print('%s：%s，跳过%s步' % (step, '缺脚本' if not has_script else '缺密钥', step))

    out = os.path.join(os.getcwd(), '成品', '待发布', a.date)
    os.makedirs(out, exist_ok=True)
    print('成品目录：%s' % out.replace('\\', '/'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
