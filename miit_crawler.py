#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
工业和信息化部（miit.gov.cn）《道路机动车辆生产企业及产品公告》新产品公示 爬虫

用法（二选一）：
    A. 在脚本顶部“配置区”填写 URL = "公告URL"，然后直接运行：python miit_crawler.py
    B. 命令行传入：python miit_crawler.py <公告URL>
    例：python miit_crawler.py https://www.miit.gov.cn/datainfo/cpgg/art/2026/art_ec6e49c646f54746978e3f6ab8618639.html

可选参数：
    --output 指定输出 CSV 路径（默认输出到本脚本目录下 output/miit_gxb_<批次>.csv）
    --concurrency 并发数（默认 8）
    --retries 每个详情页失败重试次数（默认 3）
    --limit 只抓取前 N 个详情页（调试用）

流程：
    1. 打开公告页（第一层入口），从 iframe 中定位批次列表页；
    2. 从列表页解析出数据接口 /api-gateway/jpaas-publish-server/front/page/build/unit，
       分页拉取第一层列表（企业名称 / 产品商标 / 产品名称 / 产品型号 + 详情页链接）；
    3. 并发抓取第二层详情页，解析其中多个表格（基本信息表、技术参数表、
       底盘表、发动机表），统一拼装成固定的 52 列格式；
    4. 自动重试失败的请求，输出前去重（按详情页链接），保证结果稳定、不重复。
"""

import argparse
import ast
import csv
import json
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# ==========================================================================
# 配置区
# ==========================================================================
# 要爬取的公告 URL。填写后直接运行 python miit_crawler.py 即可；
# 留空 "" 时需在命令行传入：python miit_crawler.py <公告URL>
# 例：URL = "https://www.miit.gov.cn/datainfo/cpgg/art/2026/art_ec6e49c646f54746978e3f6ab8618639.html"
URL = ""

# 输出 CSV 存放目录（默认：本脚本所在目录下的 output 文件夹）
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

BASE_URL = "https://www.miit.gov.cn"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
}

# --------------------------------------------------------------------------
# 52 列固定表头（输出格式，与历史批次保持一致）
# --------------------------------------------------------------------------
CSV_HEADERS = [
    "企业名称_链接", "企业名称", "产品商标", "产品名称", "产品型号",
    "产品商标1", "产品型号1", "产品名称1", "企业名称1", "注册地址", "目录序号",
    "生产地址", "外形尺寸", "货箱栏板内尺寸", "排放依据标准", "燃料种类",
    "最高车速", "总质量", "载质量利用系数", "额定载质量", "转向型式", "整备质量",
    "轴数", "准拖挂车总质量", "轴距", "轮胎规格", "钢板弹簧片数",
    "半挂车鞍座最大允许承载质量", "轮胎数", "驾驶室准乘人数", "额定载客", "轮距",
    "接近角离去角", "反光标识生产企业", "反光标识型号", "反光标识商标",
    "防抱死制动系统", "车辆识别代号", "前悬后悬", "其它", "说明", "油耗申报值",
    "是否同期申报", "底盘ID", "底盘型号", "底盘生产企业", "底盘类别",
    "发动机型号", "发动机企业", "排量_ml", "功率_kw", "油耗",
]

# 详情页标签 -> CSV 列名（表0 基本信息、表1 技术参数、表2 底盘、表3 发动机）
LABEL_MAP = {
    # 表0 基本信息
    "产品商标：": "产品商标1",
    "产品型号：": "产品型号1",
    "产品名称：": "产品名称1",
    "企业名称：": "企业名称1",
    "注册地址：": "注册地址",
    "目录序号：": "目录序号",
    "生产地址：": "生产地址",
    # 表1 技术参数
    "外形尺寸(mm)：": "外形尺寸",
    "货箱栏板内尺寸(mm)：": "货箱栏板内尺寸",
    "排放依据标准：": "排放依据标准",
    "燃料种类：": "燃料种类",
    "最高车速(km/h)：": "最高车速",
    "总质量(kg)：": "总质量",
    "载质量利用系数：": "载质量利用系数",
    "额定载质量(kg)：": "额定载质量",
    "转向型式：": "转向型式",
    "整备质量(kg)：": "整备质量",
    "轴数：": "轴数",
    "准拖挂车总质量(kg)：": "准拖挂车总质量",
    "轴距(mm)：": "轴距",
    "轮胎规格：": "轮胎规格",
    "钢板弹簧片数（前/后）：": "钢板弹簧片数",
    "半挂车鞍座最大允许承载质量(kg)：": "半挂车鞍座最大允许承载质量",
    "轮胎数：": "轮胎数",
    "驾驶室准乘人数（人）：": "驾驶室准乘人数",
    "额定载客（含驾驶员）（座位数）：": "额定载客",
    "轮距（前/后)mm：": "轮距",
    "接近角/离去角（度）：": "接近角离去角",
    "反光标识生产企业：": "反光标识生产企业",
    "反光标识型号：": "反光标识型号",
    "反光标识商标：": "反光标识商标",
    "防抱死制动系统：": "防抱死制动系统",
    "车辆识别代号（VIN）：": "车辆识别代号",
    "前悬/后悬(mm)：": "前悬后悬",
    "其它：": "其它",
    "说明：": "说明",
    "油耗申报值(L/100km)：": "油耗申报值",
    # 表2 底盘
    "是否同期申报": "是否同期申报",
    "底盘ID": "底盘ID",
    "底盘型号": "底盘型号",
    "底盘生产企业": "底盘生产企业",
    "底盘类别": "底盘类别",
    # 表3 发动机
    "发动机型号": "发动机型号",
    "发动机企业": "发动机企业",
    "排量(ml)": "排量_ml",
    "功率(kw)": "功率_kw",
    "油耗(L/100km)": "油耗",
}


def normalize_label(label):
    """标签兜底归一化：去掉冒号/空白/括号内容，用于未命中精确匹配时再试一次。"""
    s = label.strip()
    s = re.sub(r"[：:]$", "", s)          # 去掉结尾冒号
    s = s.replace("（", "(").replace("）", ")")
    s = re.sub(r"\([^)]*\)", "", s)      # 去掉括号内单位
    s = s.replace("(", "").replace(")", "")
    s = re.sub(r"\s+", "", s)
    return s


_NORMALIZED_MAP = {
    normalize_label(k): v for k, v in LABEL_MAP.items()
}


def map_label(label):
    """标签 -> CSV 列名；先精确匹配，再归一化兜底，匹配不到返回 None。"""
    label = label.strip()
    if label in LABEL_MAP:
        return LABEL_MAP[label]
    return _NORMALIZED_MAP.get(normalize_label(label))


# --------------------------------------------------------------------------
# HTTP 请求（带重试）
# --------------------------------------------------------------------------
_thread_local = threading.local()


def get_session():
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(HEADERS)
        _thread_local.session = session
    return session


def http_get(url, referer=None, params=None, timeout=30):
    """GET 请求；失败抛异常由调用方重试。"""
    session = get_session()
    headers = {}
    if referer:
        headers["Referer"] = referer
    resp = session.get(url, headers=headers, params=params, timeout=timeout)
    resp.raise_for_status()
    return resp


def fetch_with_retry(fn, retries=3, backoff=2.0, logger=None, context=""):
    """通用重试：fn() 抛出异常时按指数退避重试。context 用于标明是哪个请求。"""
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries:
                wait = backoff * (2 ** (attempt - 1))
                if logger:
                    logger.warning(
                        "[重试] %s 第 %d/%d 次失败：%s，%.1fs 后重试",
                        context or "请求", attempt, retries, exc, wait,
                    )
                time.sleep(wait)
    raise last_err


def log_step(logger, step_no, total, title):
    """执行步骤展示：第 N/总数 步。"""
    logger.info("")
    logger.info("========== 第 %d/%d 步：%s ==========", step_no, total, title)


def _is_tty():
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def report_progress(logger, phase, done, total, failed=0, extra=""):
    """抓取进度：交互终端下用单行实时刷新，非终端下按进度点打印日志。"""
    pct = (done / total * 100) if total else 100
    text = "%s：%d/%d (%3.0f%%)  失败 %d %s" % (phase, done, total, pct, failed, extra)
    if _is_tty():
        sys.stdout.write("\r\x1b[2K" + text)
        sys.stdout.flush()
        if done == total:
            sys.stdout.write("\n")
    elif done == total or done % 25 == 0:
        logger.info("%s", text)


# --------------------------------------------------------------------------
# 第一层：定位列表页 & 分页拉取列表
# --------------------------------------------------------------------------
def extract_iframe_src(article_html):
    """从公告页 HTML 提取嵌套列表页 iframe 的 src。"""
    m = re.search(r'<iframe[^>]*src="([^"]+)"', article_html)
    return m.group(1) if m else None


def extract_unit_script(list_html):
    """从列表页 HTML 提取数据单元脚本：返回 (queryData字典, unitUrl)。"""
    m = re.search(
        r'<script[^>]*queryData="([^"]*)"[^>]*url="([^"]*)"[^>]*>',
        list_html,
    )
    if not m:
        # 属性顺序可能不同，退而求其次分别找
        m = re.search(r'<script[^>]*queryData="([^"]*)"', list_html)
        if not m:
            raise RuntimeError("列表页中未找到 queryData 配置（页面结构可能已变化）")
        query_data = m.group(1)
        u = re.search(r'<script[^>]*url="([^"]*)"', list_html)
        unit_url = u.group(1) if u else "/api-gateway/jpaas-publish-server/front/page/build/unit"
    else:
        query_data, unit_url = m.group(1), m.group(2)
    # 单引号 JS 对象字面量本身即合法 Python 字面量
    return ast.literal_eval(query_data), unit_url


def parse_list_rows(html):
    """解析接口返回的列表表格，返回 [{url,企业名称,产品商标,产品名称,产品型号}]。"""
    soup = BeautifulSoup(html, "lxml")
    rows = []
    table = soup.find("table")
    if table is None:
        return rows
    for tr in table.find_all("tr"):
        # 表头行（含 <th>）跳过
        if tr.find("th"):
            continue
        a = tr.find("a", href=True)
        if a is None:
            continue
        # 只取可见列（隐藏列带 display:none），顺序即 企业名称/产品商标/产品名称/产品型号
        visible = [
            td.get_text(" ", strip=True)
            for td in tr.find_all("td")
            if "display:none" not in (td.get("style") or "")
        ]
        if len(visible) < 4:
            continue
        rows.append({
            "url": urljoin(BASE_URL, a["href"]),
            "企业名称": visible[0],
            "产品商标": visible[1],
            "产品名称": visible[2],
            "产品型号": visible[3],
        })
    return rows


def fetch_all_list_rows(unit_url, query_data, page_size, retries, logger, batch=""):
    """分页拉取第一层全部列表；返回 (rows, list_page_url)。"""
    url = urljoin(BASE_URL, unit_url)
    rows, seen, page_no = [], set(), 1
    search = "{}"
    if batch:
        search = json.dumps(
            {"title": "", "PICI": batch, "QYMC": "", "CPSB": "", "CPMC": "", "CPXH": ""},
            ensure_ascii=False,
        )
    while True:
        param_json = json.dumps(
            {"pageNo": page_no, "pageSize": page_size,
             "loadEnabled": True, "search": search},
            ensure_ascii=False,
        )
        params = dict(query_data)
        params["paramJson"] = param_json

        def _fetch_unit_page():
            resp = http_get(url, referer=url, params=params)
            payload = resp.json()
            if not payload.get("success"):
                raise RuntimeError(
                    "数据接口返回失败: %s" % payload.get("msg") or payload.get("code")
                )
            return payload["data"]["html"]

        html = fetch_with_retry(
            _fetch_unit_page, retries=retries, logger=logger,
            context="列表第 %d 页" % page_no,
        )
        page_rows = parse_list_rows(html)
        new_rows = [r for r in page_rows if r["url"] not in seen]
        for r in new_rows:
            seen.add(r["url"])
        rows.extend(new_rows)
        logger.info("列表第 %d 页：获取 %d 条，累计 %d 条", page_no, len(new_rows), len(rows))
        if len(page_rows) < page_size:
            break
        page_no += 1
    # 记录在列表中的原始顺序，用于最终输出按列表顺序排列
    for i, r in enumerate(rows):
        r["order"] = i
    return rows


# --------------------------------------------------------------------------
# 第二层：详情页解析
# --------------------------------------------------------------------------
def iter_label_value(table):
    """遍历表格中 标签：值 形式的 th/td 对。标签以全角冒号结尾。"""
    cells = table.find_all(["td", "th"])
    i = 0
    while i < len(cells) - 1:
        label = cells[i].get_text(" ", strip=True)
        if label.endswith("："):
            value = cells[i + 1].get_text(" ", strip=True)
            yield label, value
            i += 2
        else:
            i += 1


def parse_header_table(table, row, logger):
    """解析“表头行 + 数据行”形式的表格（底盘表/发动机表）。"""
    trs = table.find_all("tr")
    if len(trs) < 2:
        return
    headers = [c.get_text(" ", strip=True) for c in trs[0].find_all(["td", "th"])]
    values = [c.get_text(" ", strip=True) for c in trs[1].find_all(["td", "th"])]
    for h, v in zip(headers, values):
        col = map_label(h)
        if col:
            row[col] = v
        elif logger:
            logger.warning("未识别的表头字段：%r", h)


def parse_detail(html, url, logger):
    """解析详情页多个表格，返回 列名->值 字典。"""
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    row = {}
    # 表0：基本信息；表1：技术参数 —— 均为 标签：值 形式
    for ti in (0, 1):
        if ti >= len(tables):
            continue
        for label, value in iter_label_value(tables[ti]):
            col = map_label(label)
            if col:
                row[col] = value
            elif logger:
                logger.warning("未识别的标签字段：%r", label)
    # 表2：底盘；表3：发动机
    for ti in (2, 3):
        if ti >= len(tables):
            continue
        parse_header_table(tables[ti], row, logger)
    return row


# --------------------------------------------------------------------------
# 并发抓取详情页
# --------------------------------------------------------------------------
def build_output_row(list_item, detail_values):
    """把第一层字段 + 第二层字段拼装成 52 列顺序的列表。"""
    ordered = {}
    for h in CSV_HEADERS:
        ordered[h] = ""
    ordered["企业名称_链接"] = list_item["url"]
    for f in ("企业名称", "产品商标", "产品名称", "产品型号"):
        ordered[f] = list_item.get(f, "")
    ordered.update(detail_values or {})
    return [ordered[h] for h in CSV_HEADERS]


def crawl_detail(list_item, retries, logger):
    """抓取单个详情页，返回 (list_item, detail_values) 或 (list_item, None)。"""
    url = list_item["url"]
    try:
        html = fetch_with_retry(
            lambda: http_get(url, referer=url).text,
            retries=retries,
            logger=logger,
            context="详情页",
        )
        return list_item, parse_detail(html, url, logger)
    except Exception as exc:  # noqa: BLE001
        logger.error("详情页抓取失败：%s (%s)", url, exc)
        return list_item, None


def run(argv=None):
    parser = argparse.ArgumentParser(
        description="工信部道路机动车辆公告 新产品公示 爬虫（第二层详情页自动拼接）"
    )
    parser.add_argument("url", nargs="?", default="",
                        help="公告页 URL（也可在脚本顶部配置区 URL= 中填写）")
    parser.add_argument("--output", help="输出 CSV 路径（默认 output/miit_gxb_<批次>.csv）")
    parser.add_argument("--concurrency", type=int, default=8, help="并发数（默认 8）")
    parser.add_argument("--retries", type=int, default=3, help="失败重试次数（默认 3）")
    parser.add_argument("--limit", type=int, default=0, help="只抓取前 N 条详情（调试用，0 表示全部）")
    args = parser.parse_args(argv)

    article_url = args.url or URL
    if not article_url:
        parser.error(
            "未指定公告 URL：请在脚本顶部配置区填写 URL = \"...\"，"
            "或命令行传入 python miit_crawler.py <公告URL>"
        )

    # 日志走 stderr，stdout 留给进度条
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    logger = logging.getLogger("miit")

    TOTAL_STEPS = 7
    step = 0

    # ================= 第 1 步：公告页 -> iframe 列表页 =================
    step += 1
    log_step(logger, step, TOTAL_STEPS, "解析公告页，定位批次列表页")
    logger.info("公告页：%s", article_url)
    article_html = fetch_with_retry(
        lambda: http_get(article_url, referer=article_url).text,
        retries=args.retries,
        logger=logger,
        context="公告页",
    )
    iframe_src = extract_iframe_src(article_html)
    list_url = urljoin(BASE_URL, iframe_src) if iframe_src else article_url
    logger.info("定位到列表页：%s", list_url)

    # ================= 第 2 步：列表页 -> 数据接口配置 =================
    step += 1
    log_step(logger, step, TOTAL_STEPS, "解析列表页数据接口")
    list_html = fetch_with_retry(
        lambda: http_get(list_url, referer=article_url).text,
        retries=args.retries,
        logger=logger,
        context="列表页",
    )
    query_data, unit_url = extract_unit_script(list_html)
    logger.info("数据接口：%s", urljoin(BASE_URL, unit_url))

    # ================= 第 3 步：识别批次号 =================
    step += 1
    log_step(logger, step, TOTAL_STEPS, "识别批次号")
    batch = ""
    m = re.search(r"xcpgs(\d+)", list_url)
    if m:
        batch = m.group(1)
    else:
        m = re.search(r"第\s*(\d+)\s*批", article_html)
        if m:
            batch = m.group(1)
    logger.info("识别批次：%s", batch or "未知")

    # ================= 第 4 步：分页拉取第一层列表 =================
    step += 1
    log_step(logger, step, TOTAL_STEPS, "分页拉取第一层列表")
    list_rows = fetch_all_list_rows(
        unit_url, query_data, page_size=100,
        retries=args.retries, logger=logger, batch=batch,
    )
    logger.info("第一层列表共 %d 条", len(list_rows))

    # ================= 第 5 步：并发抓取第二层详情页 =================
    step += 1
    log_step(logger, step, TOTAL_STEPS, "并发抓取第二层详情页")
    if args.limit:
        list_rows = list_rows[: args.limit]
        logger.info("调试模式：仅抓取前 %d 条", args.limit)

    results = []          # (list_item, detail_values or None)
    failed_urls = []      # 重试队列
    done = 0

    def _worker(item):
        return crawl_detail(item, args.retries, logger)

    total = len(list_rows)
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(_worker, item): item for item in list_rows}
        for fut in as_completed(futures):
            item, values = fut.result()
            results.append((item, values))
            done += 1
            if values is None:
                failed_urls.append(item)
            report_progress(logger, "详情抓取", done, total, failed=len(failed_urls))

    # ================= 第 6 步：补抓失败的详情页 =================
    step += 1
    log_step(logger, step, TOTAL_STEPS, "补抓失败的详情页")
    extra_rounds = 2
    for round_no in range(1, extra_rounds + 1):
        if not failed_urls:
            break
        pending = list(failed_urls)
        failed_urls.clear()
        logger.info("第 %d/%d 轮补抓：%d 条待处理", round_no, extra_rounds, len(pending))
        done_r = 0
        rec_r = 0
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            futures = {pool.submit(_worker, item): item for item in pending}
            for fut in as_completed(futures):
                item, values = fut.result()
                for i, (li, v) in enumerate(results):
                    if li["url"] == item["url"]:
                        results[i] = (li, values)
                        break
                if values is None:
                    failed_urls.append(item)
                else:
                    rec_r += 1
                done_r += 1
                report_progress(logger, "补抓第%d轮" % round_no, done_r, len(pending),
                                failed=len(failed_urls))
        logger.info("第 %d 轮补抓完成：恢复 %d 条，剩余 %d 条", round_no, rec_r, len(failed_urls))

    # ================= 第 7 步：去重并写出 CSV =================
    step += 1
    log_step(logger, step, TOTAL_STEPS, "去重并写出 CSV")
    seen_urls = set()
    out_rows = []
    for item, values in sorted(results, key=lambda iv: iv[0].get("order", 0)):
        if item["url"] in seen_urls:
            logger.warning("去重：跳过重复链接 %s", item["url"])
            continue
        seen_urls.add(item["url"])
        out_rows.append(build_output_row(item, values))

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = args.output or os.path.join(
        OUTPUT_DIR,
        f"miit_gxb_{batch}.csv" if batch else "miit_gxb_output.csv",
    )
    # utf-8-sig：带 BOM，Excel 双击打开不乱码
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_HEADERS)
        writer.writerows(out_rows)

    n_failed = sum(1 for _, v in results if v is None)
    logger.info("完成：写入 %d 行 -> %s", len(out_rows), out_path)
    logger.info("汇总：列表 %d 条 / 成功 %d 条 / 最终失败 %d 条",
                len(list_rows), len(out_rows) - n_failed, n_failed)
    if n_failed:
        logger.warning("以下详情页最终失败（已仅保留第一层基本信息）：")
        for item, v in results:
            if v is None:
                logger.warning("  %s", item["url"])
    return 0


if __name__ == "__main__":
    sys.exit(run())
