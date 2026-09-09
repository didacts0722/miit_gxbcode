#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""miit_gxb -> mj_gxb 转换核心逻辑（供 miit_crawler 与 convert_to_mj 复用）。

转换规则（与 mj_gxb_409 的 SQL 一致）：
    - 第一列插入 pici 批次标识
    - 丢弃 企业名称_链接 / 产品商标1 / 产品型号1 / 产品名称1 / 企业名称1
    - 技术参数列名补上单位后缀
    - 底盘ID 历史批次无此字段，置空占位

输出格式与数据库导出（mj_gxb_409）一致：全字段双引号 + 无 BOM + CRLF。
"""
import csv
import re

# 输出列定义：(目标列名, 源列名)；src 为 None 表示该列置空；pici 由批次号填充
MJ_COLUMNS = [
    ("pici", None),
    ("产品商标", "产品商标"),
    ("产品型号", "产品型号"),
    ("产品名称", "产品名称"),
    ("企业名称", "企业名称"),
    ("注册地址", "注册地址"),
    ("目录序号", "目录序号"),
    ("生产地址", "生产地址"),
    ("外形尺寸(mm)", "外形尺寸"),
    ("货箱栏板内尺寸(mm)", "货箱栏板内尺寸"),
    ("排放依据标准", "排放依据标准"),
    ("燃料种类", "燃料种类"),
    ("最高车速(km/h)", "最高车速"),
    ("总质量(kg)", "总质量"),
    ("载质量利用系数", "载质量利用系数"),
    ("额定载质量(kg)", "额定载质量"),
    ("转向型式", "转向型式"),
    ("整备质量(kg)", "整备质量"),
    ("轴数", "轴数"),
    ("准拖挂车总质量(kg)", "准拖挂车总质量"),
    ("轴距(mm)", "轴距"),
    ("轮胎规格", "轮胎规格"),
    ("钢板弹簧片数（前/后）", "钢板弹簧片数"),
    ("半挂车鞍座最大允许承载质量(kg)", "半挂车鞍座最大允许承载质量"),
    ("轮胎数", "轮胎数"),
    ("驾驶室准乘人数（人）", "驾驶室准乘人数"),
    ("额定载客（含驾驶员）（座位数）", "额定载客"),
    ("轮距（前/后)mm", "轮距"),
    ("接近角/离去角（度）", "接近角离去角"),
    ("反光标识生产企业", "反光标识生产企业"),
    ("反光标识型号", "反光标识型号"),
    ("反光标识商标", "反光标识商标"),
    ("防抱死制动系统", "防抱死制动系统"),
    ("车辆识别代号（VIN）", "车辆识别代号"),
    ("前悬/后悬(mm)", "前悬后悬"),
    ("其它", "其它"),
    ("说明", "说明"),
    ("油耗申报值(L/100km)", "油耗申报值"),
    ("是否同期申报", "是否同期申报"),
    ("底盘ID", None),
    ("底盘型号", "底盘型号"),
    ("底盘生产企业", "底盘生产企业"),
    ("底盘类别", "底盘类别"),
    ("发动机型号", "发动机型号"),
    ("发动机企业", "发动机企业"),
    ("排量(ml)", "排量_ml"),
    ("功率(kw)", "功率_kw"),
    ("油耗(L/100km)", "油耗"),
]


# 修缮「车辆识别代号」：按连续 [字母数字×] 切段（保留 × 掩码），统一逗号分隔。
# 空 / ' ' / '-'（无信息约定）输出空字符串。供 miit_crawler 与 mj_convert 复用。
VIN_SEG_RE = re.compile(r"[A-Za-z0-9×]+")


def revise_vin(value):
    return ",".join(VIN_SEG_RE.findall(value or ""))


def convert_csv(in_path, out_path, batch):
    """读取 miit_gxb CSV 并写出 mj_gxb CSV，返回转换行数。

    源表头缺少必需列、或存在行宽异常时抛 ValueError。
    """
    with open(in_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = {name: i for i, name in enumerate(header)}
        rows = list(reader)

    # 校验源表头是否包含全部需要的列
    missing = [src for _, src in MJ_COLUMNS if src and src not in idx]
    if missing:
        raise ValueError("源表头缺少列：%s" % ", ".join(missing))

    # 行宽校验
    bad = [i for i, r in enumerate(rows, start=2) if len(r) != len(header)]
    if bad:
        raise ValueError("第 %s 行列数异常（%d 列 != 表头 %d 列）" % (
            bad[0], len(rows[bad[0] - 2]), len(header)))

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        # 与数据库导出格式一致：全字段引号 + 无 BOM + CRLF
        writer = csv.writer(f, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        writer.writerow([t for t, _ in MJ_COLUMNS])
        for r in rows:
            writer.writerow([
                str(batch) if t == "pici"
                else "" if src is None
                else r[idx[src]]
                for t, src in MJ_COLUMNS
            ])
    return len(rows)
