#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""命令行转换 miit_gxb_XXX.csv -> mj_gxb_XXX.csv（核心逻辑见 mj_convert.py）。

用法：
    # 不指定批次：自动转换批次号最大的文件
    python convert_to_mj.py

    # 指定批次：校验该批次文件存在后转换
    python convert_to_mj.py --batch 410
"""
import argparse
import glob
import os
import re
import sys

from mj_convert import convert_csv

# 输入/输出目录（本脚本同级目录下的 output；convert 前/后分开两个子目录）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
MIIT_IN_DIR = os.path.join(OUTPUT_DIR, "miit_gxb")  # 输入：爬虫原始（convert 前）
MJ_OUT_DIR = os.path.join(OUTPUT_DIR, "mj_gxb")     # 输出：转换后（convert 后）

BATCH_RE = re.compile(r"miit_gxb_(\d+)\.csv$")


def detect_max_batch():
    """扫描 output/miit_gxb 目录，返回批次号最大的批次（数值比较），无文件返回 None。"""
    batches = []
    for path in glob.glob(os.path.join(MIIT_IN_DIR, "miit_gxb_*.csv")):
        m = BATCH_RE.search(path)
        if m:
            batches.append(int(m.group(1)))
    return max(batches) if batches else None


def run(argv=None):
    parser = argparse.ArgumentParser(description="miit_gxb -> mj_gxb CSV 转换")
    parser.add_argument("--batch", default=None,
                        help="批次号，如 410；省略时自动取批次号最大的文件")
    parser.add_argument("--output", default="", help="输出 CSV（默认 output/mj_gxb/mj_gxb_<批次>.csv）")
    args = parser.parse_args(argv)

    # 确定批次号：未指定则自动取最大
    if args.batch is None:
        batch = detect_max_batch()
        if batch is None:
            sys.exit("错误：%s 下未找到 miit_gxb_*.csv 文件" % MIIT_IN_DIR)
        print("未指定批次，自动选择批次号最大的：%d" % batch)
    else:
        batch = str(args.batch)

    # 校验指定批次的输入文件是否存在
    in_path = os.path.join(MIIT_IN_DIR, "miit_gxb_%s.csv" % batch)
    if not os.path.isfile(in_path):
        sys.exit("错误：批次 %s 的输入文件不存在：%s" % (batch, in_path))

    out = args.output or os.path.join(MJ_OUT_DIR, "mj_gxb_%s.csv" % batch)
    out_dir = os.path.dirname(out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    try:
        n = convert_csv(in_path, out, batch)
    except ValueError as exc:
        sys.exit("转换失败：%s" % exc)
    print("转换完成：批次 %s，%d 行 -> %s" % (batch, n, out))


if __name__ == "__main__":
    run()
