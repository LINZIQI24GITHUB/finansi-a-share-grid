# A股网格回测

**A股网格回测**：按档位模拟低买高卖，回答“这只票适不适合做网格、格宽设多少、每格放多少钱、会不会被佣金和 T+1 吃死”。

A股网格交易回测：按档位模拟低买高卖，回答一个很具体的问题——

> 这只票适不适合做网格？格宽设多少？每格放多少钱？会不会被佣金和 T+1 吃死？

网格不是“策略信号”，而是一套**库存管理规则**：

```text
价格跌到下一档 → 买入一份
价格涨回上一档 → 卖出那一份
每个档位最多持一份；卖掉后可以再次触发
```

所以它和均线/RSI 回测是两种东西：成交靠“价格触及档位”，收益靠“库存周转”。

![300750 grid example](examples/grid-300750.png)

图表标题带「股票简称 + 代码」；正文依次是权益曲线（对照买入持有）、回撤和绩效表。

## 为什么需要单独一个网格引擎

普通的信号回测没法回答网格的问题：

- **T+1**：当天买入的档位当天不能卖，日内反弹那一段利润吃不到。
- **最低佣金 5 元**：每格只赚几十块时，佣金会吃掉大部分利润。
- **整手**：每格金额买不起一手，这个档位根本不会成交。
- **一字板**：涨停/跌停一字板不成交，不能假设挂单一定成交。
- **破网**：价格跌破网格下沿后不再自动买入，浮亏会留在账上。

这个 Skill 把这些约束写进回测，而不是只画一条“完美网格”的曲线。

## 安装

```bash
git clone https://github.com/LINZIQI24GITHUB/finansi-a-share-grid.git
```

放到 Agent 的 skills 目录：

```text
Claude Code   ~/.claude/skills/a-share-grid/
Codex         ~/.codex/skills/a-share-grid/
Cursor        ~/.cursor/skills/a-share-grid/
通用           ~/.agents/skills/a-share-grid/
```

Windows 示例：

```powershell
New-Item -ItemType Directory -Force "$HOME\.agents\skills" | Out-Null
git clone https://github.com/LINZIQI24GITHUB/finansi-a-share-grid.git "$HOME\.agents\skills\a-share-grid"
```

依赖：

```bash
cd a-share-grid
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
pip install -r requirements.txt
```

Python 3.11+；需要 pandas、numpy、pyarrow、matplotlib、eltdx。

## 快速开始

```bash
# 跑一次网格
python scripts/run.py run \
  --code 300750 --start 2024-01-01 --end 2025-12-31 \
  --step 2 --levels 10 --amount 20000 --cash 200000

# 参数扫描：格宽 × 档数
python scripts/run.py sweep \
  --code 300750 --start 2024-01-01 --end 2025-12-31 \
  --amount 20000 --cash 200000

# 离线自检（需要本地缓存）
python scripts/run.py demo
```

也可以直接在 Agent 里说：

```text
用 a-share-grid 回测 300750 从 2024-01-01 到 2025-12-31 的网格：
格宽 2%、10 档、每格 2 万、本金 20 万，并画出权益图和回撤。
```

## 参数

| 参数 | 默认 | 说明 |
|---|---:|---|
| `--code` | 必填 | 6 位代码，或股票名称 |
| `--start` / `--end` | 必填 | 回测区间；建议覆盖一段震荡 + 一段单边 |
| `--step` | `2` | 格宽（%）；相邻档位价差 |
| `--levels` | `10` | 向下档数；网格区间约为锚点 × (1 ± levels × step) |
| `--amount` | `10000` | 每格金额；**必须 ≥ 一手成本**，否则大量档位不成交 |
| `--cash` | `200000` | 本金 |
| `--base-lots` | `0` | 初始底仓档数 |
| `--anchor` | 首日收盘 | 网格锚点 |
| `--plot` | `out/grid_<code>_<step>_<levels>.png` | 权益图路径 |
| `--no-plot` | — | 不生成图 |
| `--json` | — | 输出 JSON 统计，便于下游处理 |

## 输出

终端会给出：

- 网格收益 vs 买入持有
- 网格区间、锚点
- 卖出/买入次数
- 每格平均利润、单格毛利
- 费用及占本金比例
- 最大库存、期末持仓、未平仓浮亏
- 破网天数
- T+1 / 资金不足 / 买不起一手的档位统计
- 最近 6 笔成交

默认同时生成 PNG：

```text
out/grid_300750_2_10.png
```

图表包含：

- 网格权益 vs 买入持有
- 回撤
- 累计收益、年化、最大回撤、波动率、夏普、胜率、盈亏比
- 风险提示

## 示例：单边上涨时，网格会跑输

以 300750 在 2024-01-02 ~ 2025-12-31 的样例：

```text
网格收益    20.34%
买入持有   139.85%
超额      -119.50%
卖出 60 次，费用 1,131 元
```

这不是 bug，是网格的本性：单边上涨时它不断卖出，赚的是小波段，错过的是主升浪。

网格真正有价值的地方是：

- 震荡市里反复吃档差
- 回撤相对可控
- 有明确的库存和破网边界

**不要用“胜率”判断网格。** 网格的胜率天然接近 100%（每格涨一格就卖），真正该看的是：

```text
网格收益 vs 买入持有的差额
每格平均利润
费用占本金比例
最大库存
破网天数
未平仓浮亏
```

## 数据与缓存

数据源是 `eltdx`（通达信协议），默认缓存在：

```text
<skill>/data/bars/{code}.{adjust}.parquet
<skill>/data/manifest.json
```

也可以指定：

```bash
python scripts/run.py --data-dir /path/to/data run ...
```

首次运行需要能连通行情服务器。仓库**不包含任何原始行情数据**；请自行确认数据源的再分发许可。

## 边界

- 只做单标的日频网格；不做组合、行业轮动、对冲。
- 不模拟盘口排队、滑点、冲击成本；成交按档位/开盘价规则近似。
- 不处理分红再投资的逐笔现金流；收益口径使用后复权序列，并在窗口首日按真实价格缩放。
- 不保证实盘能成交；一字板、停牌、流动性不足都会改变结果。
- 参数扫描只用于看趋势，不能拿同一段数据挑最优参数当未来收益。
- 这是研究工具，不是投资建议，也不承诺收益。

## License

MIT. See [LICENSE](LICENSE).
