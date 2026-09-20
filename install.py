#!/usr/bin/env python3
"""Copy the skill into an explicitly chosen skills directory; never overwrite."""
import argparse
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--to', type=Path, default=Path.home() / '.agents' / 'skills')
    args = parser.parse_args()
    source = Path(__file__).resolve().parent / 'lrc-sync'
    destination = args.to.expanduser().resolve() / 'lrc-sync'
    if destination.exists():
        parser.error(f'目标已存在，未覆盖：{destination}。更新前请先备份旧版。')
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    except OSError as exc:
        parser.exit(1, f'安装失败：{exc}\n')
    print(f'已安装：{destination / "SKILL.md"}')
    print('在 Codex 中使用 $lrc-sync；未显示时重启 Codex。')


if __name__ == '__main__':
    main()
