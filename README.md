# miit_gxbcode

工信部《道路机动车辆生产企业及产品公告》新产品公示的**数据抓取 + 格式转换**工具。

纯 Python + 纯 CSV 管线，不依赖数据库。从官方公示页抓取整车新产品申报数据，输出两层 CSV：

| 文件 | 说明 |
|---|---|
| `output/miit_gxb_<批次>.csv` | 爬虫原始产出，52 列，UTF-8-SIG（带 BOM，Excel 直接打开不乱码） |
| `output/mj_gxb_<批次>.csv` | 转换后标准格式，48 列，全字段双引号 + 无 BOM + CRLF，与库内 `mj_gxb_409` 导出格式一致 |

数据来源：工业和信息化部官网公告公示（https://www.miit.gov.cn ）。

## 数据流

```
公告页 URL（某批次公示入口）
   │
   ▼
[1] miit_crawler.py ──────────► output/miit_gxb_<批次>.csv   （52 列原始明细）
   │                               │
   │ （自动转换，除非 --no-mj）      ▼
   └─────────────────► [2] mj_convert.convert_csv ──► output/mj_gxb_<批次>.csv（48 列标准格式）
```

## 快速开始

### 环境准备

```bash
pip install -r requirements.txt
```

依赖：`requests` / `beautifulsoup4` / `lxml`（版本见 `requirements.txt`，已适配 Python 3.14）。

### 1. 抓取公示数据（含自动转换）

命令行传入公告页 URL，例如第 411 批次：

```bash
python miit_crawler.py https://www.miit.gov.cn/datainfo/cpgg/art/2026/art_389774fa3c864066a544d3a7f7053eb2.html
```

也可以在脚本顶部「配置区」填写 `URL = "..."` 后直接运行 `python miit_crawler.py`。

产出：

- `output/miit_gxb_411.csv`
- `output/mj_gxb_411.csv`（自动转换；加 `--no-mj` 可跳过）

### 2. 仅做格式转换（已有 miit 原始 CSV）

```bash
python convert_to_mj.py              # 不指定批次：自动转换批次号最大的文件
python convert_to_mj.py --batch 410  # 指定批次
```

### 3. 校验输出结构（本地调试）

对照参考文件 `miit_gxb_409.csv` 检查表头一致 / 行宽 / 链接唯一 / 各列填充率等。该脚本用相对路径引用参考文件，需在 `output` 目录下运行：

```bash
cd output
python ../validate_output.py miit_gxb_411.csv
```

> `validate_output.py` 是本地调试脚本，已在 `.gitignore` 中排除，不随仓库提交。

## 爬虫工作流程（miit_crawler.py，7 步）

| 步骤 | 处理 |
|---|---|
| 1 | 打开公告页，从 iframe 定位批次列表页 |
| 2 | 解析列表页数据接口 `queryData` + `unitUrl` |
| 3 | 识别批次号（列表页 URL `xcpgs<数字>` 或公告页「第 N 批」） |
| 4 | 分页拉取第一层列表（企业名称 / 产品商标 / 产品名称 / 产品型号 + 详情链接） |
| 5 | 并发抓取第二层详情页，解析 4 张表（基本信息 / 技术参数 / 底盘 / 发动机） |
| 6 | 失败的详情页做 2 轮补抓重试 |
| 7 | 按链接去重 + 按列表顺序排序，写出 `miit_gxb_<批次>.csv` |

请求带线程级 Session 复用与指数退避重试；抓取对象为官网公开公示数据，请合理控制并发与频率。

## 命令行参数

`miit_crawler.py`：

| 参数 | 默认 | 说明 |
|---|---|---|
| `url`（位置参数） | 顶部配置区 `URL` | 公告页 URL，二者必填其一 |
| `--output` | `output/miit_gxb_<批次>.csv` | 输出 CSV 路径 |
| `--concurrency` | 8 | 详情页抓取并发数 |
| `--retries` | 3 | 每个详情页失败重试次数 |
| `--limit` | 0（全部） | 只抓前 N 条（调试用） |
| `--no-mj` | 关闭 | 抓取后不自动转换 mj_gxb |

`convert_to_mj.py`：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--batch` | 自动取最大批次 | 指定要转换的批次号 |
| `--output` | `output/mj_gxb_<批次>.csv` | 输出 CSV 路径 |

## 目录结构

```
miit_gxbcode/
├── miit_crawler.py      # 主爬虫（入口 1）
├── mj_convert.py        # 52→48 列转换核心 + VIN 修缮（爬虫与转换脚本共享）
├── convert_to_mj.py     # 独立转换入口（入口 2）
├── validate_output.py   # 输出校验脚本（本地调试，不入库）
├── requirements.txt
├── docs/运行简报.md      # 项目运行简报（主流程说明 + 更新记录）
└── output/              # 抓取产物（数据文件，不入库）
    ├── miit_gxb_<批次>.csv
    └── mj_gxb_<批次>.csv
```

## 输出格式说明

### `miit_gxb_<批次>.csv`（52 列，UTF-8-SIG）

- 前 5 列来自第一层列表：`企业名称_链接`、企业名称、产品商标、产品名称、产品型号；
- 其余列来自详情页 4 张表（基本信息 / 技术参数 / 底盘 / 发动机），字段以标签 → 列名映射（`LABEL_MAP`）拼装；
- 失败且补抓仍失败的详情页仅保留第一层信息，其余列为空。

### `mj_gxb_<批次>.csv`（48 列，全引号 + 无 BOM + CRLF）

与数据库导出格式（`mj_gxb_409`）逐字节一致。转换规则：

- 首列插入 `pici` 批次标识；
- 丢弃 `企业名称_链接`、`产品商标1`、`产品型号1`、`产品名称1`、`企业名称1`（52 列中冗余的首层字段）；
- 技术参数列名补单位后缀（如 `外形尺寸` → `外形尺寸(mm)`）；
- `底盘ID` 置空占位（历史批次无此字段）。

## 车辆识别代号（VIN）修缮

详情页解析出的「车辆识别代号」可能含空格 / 中文逗号 / 连续逗号等脏分隔符。`mj_convert.py` 提供共享函数 `revise_vin()`：

- 按连续 `[字母数字×]` 切段，统一为英文逗号分隔，`×` 掩码完整保留；
- `' '` / `'-'` / 空（无信息约定）输出空字符串。

爬虫写 `miit_gxb` 时即调用修缮，`mj_gxb` 经转换自动继承，两输出同步干净。仅影响新爬批次，历史文件未追溯修改。

## 更新记录

- **2026-08-17**：新增「车辆识别代号」修缮逻辑（`revise_vin`），爬虫与转换共享；详见 `docs/运行简报.md`。
- **2026-08-11**：爬虫取数后自动转换为 mj_gxb 格式，抽取共享转换模块 `mj_convert`。
- **2026-08-11**：初始化仓库；`requirements.txt` 适配 Python 3.14（lxml 6.1.1）。

## 参考

- 项目运行简报（主流程 / 子流程 / 更新细节）：[docs/运行简报.md](docs/运行简报.md)
- 数据来源：工信部《道路机动车辆生产企业及产品公告》https://www.miit.gov.cn
