# Context Compression 子系统

`CAi/CAi_agent/compression/`

对话历史压缩模块。当对话轮次过多、上下文超出 LLM 窗口预算时，自动裁剪低优先级
消息，保留关键信息。零额外 LLM 调用，纯规则驱动。

## 为什么需要压缩

LLM 的上下文窗口是有限的（通常 128K~200K tokens）。在长对话中，历史消息会不断
累积，导致：

- **超出窗口限制** — API 直接报错
- **成本飙升** — token 数与费用成正比
- **注意力退化** — 即使不超限，过长的历史也会稀释 LLM 对近期上下文的关注

压缩的目标：**在不丢失关键信息的前提下，将历史消息控制在可管理的范围内**。

## 模块结构

```
compression/
├── __init__.py          # 公开 API 入口
├── _compressor.py       # ContextCompressor — 决策调度器
├── _hybrid.py           # hybrid_compress — 三区混合分区算法
├── _scoring.py          # _score_message — 消息重要性评分
└── _plan_preserve.py    # _preserve_plan — plan 块保留装饰器
```

| 模块 | 职责 | 行数 |
|------|------|------|
| `_compressor.py` | 判断是否需要压缩 → 选择策略 → 调度执行 | ~90 |
| `_hybrid.py` | 三区混合分区算法（默认策略） | ~68 |
| `_scoring.py` | 消息重要性评分 + 关键词正则 | ~55 |
| `_plan_preserve.py` | plan 块提取与保留装饰器 | ~50 |

每个模块职责单一，可独立测试和替换。

## 核心架构约束

```
用户发送消息
    │
    ▼
run_with_history_streaming(prompt, history)
    │
    ▼
_build_messages(prompt, history)
    │
    ├── _maybe_compress_history(history)   ◄── 压缩在这里发生，且仅一次
    │       │
    │       ▼
    │   ContextCompressor.compress(history)
    │       │
    │       ├── len(history) <= budget?  → 原样返回
    │       ├── 有 custom_hook?          → 尝试 hook，失败则回退
    │       └── 默认                      → hybrid_compress(history, max_pairs)
    │
    ▼
生成 messages 列表 → LLM 调用 → generate→execute→generate 循环
                                        │
                                  直接 append 到 messages
                                  ❌ 绝不可重新压缩
```

**为什么循环中不能压缩？**

generate→execute→generate 循环中，agent 会往 `messages` 列表追加自己的回复和代码
执行结果（observation）。这些是当前推理链的即时上下文——如果在循环中触发压缩，
会丢掉 agent 正在使用的 observation，导致后续推理完全脱节。

因此压缩只在用户发送消息时触发一次，循环中直接操作 `messages` 列表，不经过
`_maybe_compress_history`。这个约束在 `BaseAgent._build_messages` 的 docstring
中有明确标注。

## ContextCompressor

决策调度器，封装了"是否压缩 → 用哪个策略 → 执行"的完整逻辑。

### 构造函数

```python
from CAi.CAi_agent.compression import ContextCompressor

compressor = ContextCompressor(
    max_pairs=40,           # 预算：最多 40 对消息（= 80 条），超出则压缩
    strategy=None,          # 压缩策略，默认 hybrid_compress
    custom_hook=None,       # 优先级最高的自定义函数（兼容旧接口）
)
```

### 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `max_pairs` | `int` | `40` | 最大消息对数。内部转换为 `max_pairs * 2` 条消息 |
| `strategy` | `Callable` | `hybrid_compress` | 压缩策略函数，签名 `(history, max_pairs=N) -> list[dict]` |
| `custom_hook` | `Callable` | `None` | 旧接口兼容。签名 `(history) -> list[dict]`。优先级最高，失败回退到 strategy |

### 压缩流程

```
compress(history)
    │
    ├── len(history) <= max_pairs * 2
    │       → 返回原 history（同一对象，不拷贝）
    │
    ├── custom_hook 已设置？
    │       ├── 成功 → 返回 hook 结果
    │       └── 异常 → logger.warning + 回退到 strategy
    │
    └── 调用 strategy(history, max_pairs=max_pairs)
            → 返回压缩后的 history
```

### 调用方式

```python
# 方式一：显式调用
compressed = compressor.compress(history)

# 方式二：直接调用实例（__call__ 别名）
compressed = compressor(history)

# 方式三：传入 BaseAgent
agent = BaseAgent(compressor=compressor, ...)
```

### 与 BaseAgent 的集成

`BaseAgent` 构造函数接受三种方式配置压缩：

```python
# 推荐：传入预构建的 ContextCompressor
agent = BaseAgent(
    compressor=ContextCompressor(max_pairs=30),
    ...
)

# 兼容方式一：max_history_pairs（自动构建 ContextCompressor）
agent = BaseAgent(max_history_pairs=30, ...)

# 兼容方式二：context_compress_hook（自动构建 ContextCompressor + custom_hook）
agent = BaseAgent(
    max_history_pairs=30,
    context_compress_hook=my_hook,
    ...
)
```

`BaseAgent` 通过 property 别名保持向后兼容：

```python
agent.max_history_pairs = 20       # → agent._compressor.max_pairs = 20
agent._context_compress_hook = fn  # → agent._compressor._custom_hook = fn
```

## hybrid_compress — 三区混合分区算法

默认的压缩策略，**零额外 LLM 调用**，纯规则驱动。

### 算法概述

当历史消息数量超过预算时，将消息划分为三个区域：

```
原始历史 (120 条消息, max_pairs=10 → 预算 20 条)

┌─────────────────────────────────────────────────────────┐
│  Zone 3: 最旧的消息                                      │  ← 丢弃
│  (低优先级，如纯推理文本、早期讨论)                          │
├─────────────────────────────────────────────────────────┤
│  Zone 2: 中间消息                                        │  ← 按评分过滤
│  (保留 score >= 6 的高价值消息)                            │
│  如果仍超预算，按 score 降序排序后截断                       │
├─────────────────────────────────────────────────────────┤
│  Zone 1: 最近的消息                                      │  ← 原样保留
│  (recent_count = max_msgs // 2 = 10 条)                  │
└─────────────────────────────────────────────────────────┘

压缩后输出：
  [摘要通知] + [Zone 2 保留的消息] + [Zone 1 原样消息]
```

### 分区规则

```python
max_msgs = max_pairs * 2                  # 总预算（消息条数）
recent_count = max_msgs // 2              # Zone 1 大小（最近一半）

# Zone 1: 最近 recent_count 条 → 原样保留
recent = history[-recent_count:]

# Zone 2: 其余消息 → 只保留 score >= 6 的
middle = history[:len(history) - recent_count]
middle_kept = [m for m in middle if _score_message(m) >= 6]

# 如果 Zone 1 + Zone 2 仍超预算 → 按 score 降序截断 Zone 2
if len(middle_kept) + recent_count > max_msgs:
    middle_kept.sort(key=_score_message, reverse=True)
    middle_kept = middle_kept[:max_msgs - recent_count]

# Zone 3: 被丢弃的消息 → 生成一条摘要通知
total_dropped = len(history) - len(middle_kept) - len(recent)
```

### 输出格式

```python
[
    # 摘要通知（仅在有消息被丢弃时添加）
    {"role": "assistant",
     "content": "[注意：已省略 45 条低优先级消息以节省上下文。"
                "保留中间 8 条关键消息 + 最近 10 条原始对话。]"},

    # Zone 2: 保留的高分消息
    {"role": "user",      "content": "calculate SCScore for CC(=O)O"},
    {"role": "assistant", "content": "<observation>SCScore: 2.34</observation>"},
    ...

    # Zone 1: 最近的对话（原样）
    {"role": "user",      "content": "now try a different scaffold"},
    {"role": "assistant", "content": "<execute>...</execute>"},
    ...
]
```

### 压缩效果示例

假设 `max_pairs=5`（预算 10 条），当前历史 20 条：

```
原始 (20 条):
  [0]  user: "generate 5 analogs of scaffold c1cc1"         score=10
  [1]  assistant: "<execute>gen_analogs(...)</execute>"     score=6
  [2]  assistant: "<observation>SMILES: C1CC1C, ...</obs>" score=8
  [3]  assistant: "Here are the 5 analogs..."              score=6
  [4]  user: "calculate SCScore for all"                    score=15
  [5]  assistant: "<execute>calc_scscore(...)</execute>"    score=6
  [6]  assistant: "<observation>SCScores: 2.1, 3.4, ...</obs>" score=8
  [7]  assistant: "The SCScores are..."                     score=6
  [8]  user: "which one has the best score?"                score=10
  [9]  assistant: "Molecule C1CC1C has..."                  score=2 ← 纯推理
  [10] user: "ok now predict toxicity"                      score=10
  ...
  [15] assistant: "Let me think about this..."              score=2 ← 纯推理
  [16] user: "summarize all results"                        score=10
  [17] assistant: "<execute>summarize()</execute>"          score=6
  [18] assistant: "<observation>Summary: ...</observation>" score=8
  [19] assistant: "Here's the summary..."                   score=2 ← 纯推理

分区 (recent_count = 5):
  Zone 1 (保留): [15]~[19] — 最近 5 条原样保留
  Zone 2 (过滤): [0]~[14] — 保留 score >= 6 的 → 丢掉 [9], [15] 等纯推理

输出:
  [通知] + [Zone 2 高分消息] + [Zone 1 原样消息]
  = 约 13 条（包含通知）
```

## _score_message — 消息重要性评分

对每条消息按内容类型打分，分数越高越值得保留：

| 消息类型 | 基础分 | 关键词加分 | 总分 | 保留阈值 |
|----------|--------|-----------|------|---------|
| user 消息 | 10 | +5 | 10~15 | 始终保留 (≥6) |
| assistant + `<observation>` | 8 | — | 8 | 始终保留 (≥6) |
| assistant + 领域关键词 | 6 | — | 6 | 保留 (≥6) |
| assistant + `<execute>` | 5 | — | 5 | 可能丢弃 (<6) |
| assistant 纯推理文本 | 2 | — | 2 | 优先丢弃 (<6) |

### 评分逻辑

```python
def _score_message(msg: dict) -> int:
    role = msg.get("role", "")
    content = msg.get("content", "")

    if role == "user":
        score = 10
        if _IMPORTANT_KEYWORDS.search(content):
            score += 5
        return score

    if "<observation>" in content:
        return 8
    if _IMPORTANT_KEYWORDS.search(content):
        return 6
    if "<execute>" in content:
        return 5
    return 2
```

### 关键词正则

`_IMPORTANT_KEYWORDS` 匹配以下领域关键词（不区分大小写）：

```
分子领域:    SMILES, scaffold, .pdb, .sdf, .gro, .xtc, .top
实验参数:    num_sample, num_analogs, score, energy, docking
状态词:      success, error, output_, result, file, path
标签:        <observation>, <execute>
```

包含这些关键词的消息通常是关键数据（工具输出、文件路径、实验结果），丢弃会导致
agent 后续推理断裂。

## _preserve_plan — plan 块保留

`<execute lang="plan">` 是 agent 写入的任务计划。在长对话中，plan 可能出现在
较早的消息里，但对当前任务仍然有指导意义。

### 机制

`@_preserve_plan` 是一个装饰器，包裹在 `hybrid_compress` 外层：

```
hybrid_compress(history)
    │
    ▼  @_preserve_plan 装饰器
    │
    ├── 1. 扫描所有包含 <execute lang="plan"> 的消息
    │
    ├── 2. 记住最新的 plan 消息（latest_plan）
    │
    ├── 3. 从输入中移除所有 plan 消息，送入原始算法
    │
    ├── 4. 原始算法正常压缩
    │
    └── 5. 将 latest_plan 前置到压缩结果的最前面
            → [latest_plan] + [compressed_messages]
```

### 为什么需要这个

假设 agent 在第 5 轮写了 plan，之后执行了 30 轮代码。到第 40 轮时触发压缩，
Zone 3 会覆盖第 5 轮——plan 就丢了。`_preserve_plan` 保证最新的 plan 永远存活。

### 多条 plan 的处理

如果历史中有多条 plan 消息（agent 更新了计划），只有**最新的一条**被保留。
旧 plan 参与正常的三区压缩，可能被丢弃。

## 自定义压缩策略

### 方式一：替换 strategy

```python
def sliding_window(history, max_pairs=40):
    """只保留最近的 N 条消息，不做评分。"""
    return history[-(max_pairs * 2):]

compressor = ContextCompressor(
    max_pairs=20,
    strategy=sliding_window,
)
```

### 方式二：LLM 摘要（高级）

```python
from langchain_openai import ChatOpenAI

_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

def llm_summarize(history, max_pairs=40):
    """用 LLM 对旧消息做摘要，替换 Zone 3。"""
    recent = history[-(max_pairs):]
    old = history[:-(max_pairs)]

    # 把旧消息拼接为文本，让 LLM 生成摘要
    text = "\n".join(f"{m['role']}: {m['content'][:500]}" for m in old)
    summary = _llm.invoke(f"Summarize this conversation in 3 sentences:\n{text}")

    return [
        {"role": "assistant", "content": f"[摘要] {summary.content}"},
        *recent,
    ]

compressor = ContextCompressor(max_pairs=30, strategy=llm_summarize)
```

> 注意：LLM 摘要策略会引入额外的 API 调用和延迟。默认的 `hybrid_compress`
> 是零调用的，适合大多数场景。

### 方式三：custom_hook（兼容旧接口）

```python
def my_hook(history):
    """签名不同：只接收 history，没有 max_pairs。"""
    return history[-10:]

compressor = ContextCompressor(max_pairs=5, custom_hook=my_hook)
```

`custom_hook` 优先级最高，但如果它抛出异常，会回退到 `strategy`：

```python
def broken_hook(history):
    raise RuntimeError("something went wrong")

compressor = ContextCompressor(
    max_pairs=5,
    custom_hook=broken_hook,    # 会抛异常
    strategy=sliding_window,     # 回退到这里
)
# 结果：logger.warning + sliding_window 被调用
```

## 与 Web UI 的集成

在 Web UI 中，每次用户发送消息时的调用链：

```
前端 POST /api/chat
    │
    ▼
chat.py: event_stream()
    │  从 ConversationStore 加载完整历史
    │  history = [{"role": "user", "content": ...}, ...]
    │
    ▼
chat_service.py: async_iter_agent(agent, prompt, history)
    │
    ▼
agent.run_with_history_streaming(prompt, history)
    │
    ▼
_build_messages(prompt, history)
    │
    ├── _maybe_compress_history(history)  ◄── 压缩在这里
    │       → self._compressor.compress(history)
    │
    └── 构建 LangChain messages 列表
            → 进入 generate→execute→generate 循环
```

关键点：

- `ConversationStore` 保存的是**完整历史**（不压缩），压缩是临时的、每次请求独立计算
- 压缩后的 history 只用于当次 LLM 调用，不会写回存储
- 用户刷新页面或切换对话时，加载的仍然是完整历史

## 测试

测试文件：`tests/test_context_compression.py`

### 测试覆盖

| 类别 | 测试数量 | 覆盖内容 |
|------|---------|---------|
| 评分逻辑 | 6 | 各消息类型的分数正确性 |
| 无压缩 | 2 | 预算内返回原对象、恰好等于上限 |
| 混合分区 | 5 | 最近区域保留、低分丢弃、observation 保留、通知消息、直接调用 |
| 自定义 hook | 2 | hook 替换默认策略、hook 失败回退 |
| ContextCompressor | 8 | 预算判断、自定义策略、hook 优先级、hook 回退、可调用协议、repr、BaseAgent 集成 |

### 运行测试

```bash
# 全部压缩测试
pytest tests/test_context_compression.py -v

# 只跑 ContextCompressor 相关
pytest tests/test_context_compression.py -v -k "compressor"
```

### 关键断言

- `compress(history) is history` — 预算内返回同一对象（无拷贝开销）
- 压缩后长度 ≤ `max_msgs + 1`（+1 是通知消息）
- 通知消息包含 "已省略" 和丢弃数量
- plan 块始终出现在压缩结果的第一个位置
- `custom_hook` 抛异常时回退到 `strategy`，不会中断 agent

## 设计决策

### 为什么不用 LLM 做摘要？

| 方案 | 优点 | 缺点 |
|------|------|------|
| 规则分区（当前） | 零延迟、零成本、确定性 | 无法生成自然语言摘要 |
| LLM 摘要 | 摘要质量高 | 额外 API 调用、延迟、成本 |
| 混合（规则 + LLM） | 兼顾质量和效率 | 实现复杂 |

当前选择规则方案，因为：
1. 对话压缩是高频操作（每次用户消息都触发），不能引入额外延迟
2. agent 的消息本身就包含结构化标签（`<observation>`、`<execute>`），
   基于标签的评分已经能有效区分重要性
3. 用户可以通过 `strategy` 参数注入 LLM 摘要策略，按需使用

### 为什么 max_pairs 默认 40？

40 对 = 80 条消息。以 Anthropic Claude 为例，80 条消息通常对应 ~60K-80K tokens，
在 200K 窗口内留有充足余量给 system prompt + 当前回复。对于使用 128K 窗口的模型，
建议降到 `max_pairs=25`。

### 为什么 Zone 1 是 50% 而不是固定条数？

固定条数（如"保留最近 20 条"）在 `max_pairs` 变化时需要手动调整。百分比方案让
Zone 1 自动跟随预算缩放：`max_pairs=10` 时 Zone 1 = 10 条，`max_pairs=40` 时
Zone 1 = 40 条。最近的消息始终是 agent 推理的核心上下文，给足空间。

## 限制与未来方向

### 当前限制

1. **不支持 token 级预算** — 目前按消息条数控制，不计算实际 token 数。
   一条包含大量代码的 assistant 消息可能占用数千 tokens，但仍算作 1 条。
2. **评分启发式是硬编码的** — 关键词列表和分数阈值针对药物发现领域优化，
   其他领域可能需要调整 `_IMPORTANT_KEYWORDS` 和 `_score_message`。
3. **压缩不跨对话** — 每个对话独立压缩，无法利用跨对话的共享知识。

### 未来方向

1. **Token-budget 策略** — 基于 tiktoken 计算实际 token 数，按 token 预算裁剪
2. **可插拔评分器** — 将 `_score_message` 改为可配置的策略函数
3. **增量压缩** — 缓存上一次的压缩结果，避免每次从头计算
4. **摘要注入** — 对 Zone 3 生成一段 LLM 摘要，注入到 Zone 1 前面，保留语义连续性
