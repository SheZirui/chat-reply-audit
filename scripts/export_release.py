#!/usr/bin/env python3
"""Copy only checked public files to a new local folder. Never invokes Git or a network API."""
import argparse
import shutil
from pathlib import Path
from privacy_check import PUBLIC_FILES,ROOT,check


def export(destination):
    result=check(ROOT)
    if not result['ok']:raise ValueError('发布检查未通过；先查看 privacy_check 的结果')
    destination=Path(destination).resolve()
    if destination==ROOT or ROOT in destination.parents:
        raise ValueError('发布副本应放在项目目录以外，避免混入运行产物')
    if destination.exists():raise ValueError('目标目录已存在；请选择一个全新目录')
    destination.mkdir(parents=True)
    for rel in (*PUBLIC_FILES,'release-manifest.json'):
        target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/rel,target)
    verified=check(destination)
    if not verified['ok']:raise ValueError('发布副本校验失败，请勿上传')
    return verified


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);args=parser.parse_args()
    try:
        r=export(args.out);print(f"已生成本地发布副本：{r['allowlisted_file_count']+1}个文件。未初始化Git、未联网、未上传。")
    except (ValueError,OSError) as exc:
        print('未完成：'+(str(exc) if isinstance(exc,ValueError) else '目标无法写入'));raise SystemExit(2)
