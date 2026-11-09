# OrangeCode 1:1 完整复刻技术蓝图与功能对齐清单
> **基准版本**：`CodeFlow-harness` (0.1.7)
> **目标工程**：`orangecode`
> **目标要求**：**1:1 功能全量对齐、架构一致、严密验证、零功能遗漏**

---

## 目录
1. [总体规模与对齐现状审计](#1-总体规模与对齐现状审计)
2. [22 个子系统 1:1 详细功能矩阵与契约规范](#2-22-个子系统-11-详细功能矩阵与契约规范)
   - 2.1 [Spine 并发调度与多会话管道 (`spine`)](#21-spine-并发调度与多会话管道-spine)
   - 2.2 [Agent 运行时、子智能体与高级工具链 (`agent`)](#22-agent-运行时子智能体与高级工具链-agent)
   - 2.3 [Context Engine 分层上下文治理与装配 (`context_engine`)](#23-context-engine-分层上下文治理与装配-context_engine)
   - 2.4 [Providers 多模型适配、容灾与 Fallback (`providers`)](#24-providers-多模型适配容灾与-fallback-providers)
   - 2.5 [Routing KNN 语义模型路由 (`routing`)](#25-routing-knn-语义模型路由-routing)
   - 2.6 [Call Efficiency & Token-Wise 提示词缓存与成本核算](#26-call-efficiency--token-wise-提示词缓存与成本核算)
   - 2.7 [Sandbox 操作系统与微虚拟机级安全沙箱 (`sandbox`)](#27-sandbox-操作系统与微虚拟机级安全沙箱-sandbox)
   - 2.8 [Session 工业级会话存取与代际控制 (`session`)](#28-session-工业级会话存取与代际控制-session)
   - 2.9 [Channels 多平台消息网关 (飞书/企微/QQ) (`channels`)](#29-channels-多平台消息网关-飞书企微qq-channels)
   - 2.10 [Tracing OpenTelemetry 分布式链路追踪 (`tracing`)](#210-tracing-opentelemetry-分布式链路追踪-tracing)
   - 2.11 [Memory Engine 记忆提炼与 Skill Forge (`memory_engine`)](#211-memory-engine-记忆提炼与-skill-forge-memory_engine)
   - 2.12 [Evolver 技能自进化引擎 (`evolver`)](#212-evolver-技能自进化引擎-evolver)
   - 2.13 [Proactive Engine 定时任务调度器 (`proactive_engine`)](#213-proactive-engine-定时任务调度器-proactive_engine)
   - 2.14 [TUI RPC 跨语言双向通信总线 (`tui_rpc`)](#214-tui-rpc-跨语言双向通信总线-tui_rpc)
   - 2.15 [UI-TUI 原生终端交互前端 (`ui-tui`)](#215-ui-tui-原生终端交互前端-ui-tui)
   - 2.16 [Config 动态配置与凭据热更新 (`config`)](#216-config-动态配置与凭据热更新-config)
   - 2.17 [CLI 完整生产级命令矩阵 (`cli`)](#217-cli-完整生产级命令矩阵-cli)
   - 2.18 [Auth & Security 权限令牌与安全边界 (`auth` & `security`)](#218-auth--security-权限令牌与安全边界-auth--security)
   - 2.19 [Eval Engine 评测运行时与审计钩子 (`eval_engine`)](#219-eval-engine-评测运行时与审计钩子-eval_engine)
   - 2.20 [Plugin 插件生命周期与发现机制 (`plugin`)](#220-plugin-插件生命周期与发现机制-plugin)
   - 2.21 [Benchmarks 标准基准评测套件 (`benchmarks`)](#221-benchmarks-标准基准评测套件-benchmarks)
   - 2.22 [Templates & Onboarding 引导模板与契约文档](#222-templates--onboarding-引导模板与契约文档)
3. [1:1 全量复刻阶段实施里程碑](#3-11-全量复刻阶段实施里程碑)
4. [质量验收与对齐度校验契约](#4-质量验收与对齐度校验契约)

---

## 1. 总体规模与对齐现状审计

原项目 `CodeFlow-harness` 包含 **70,436 行 Python 代码**，外加由 Node.js 22、React、Ink 构建的原生 TUI 客户端以及 6 个 Benchmark 评测包。

### 模块规模与当前对齐对照表

| 模块名称 | 原工程文件数 / 行数 | 核心定位与技术难点 | 当前 OrangeCode 状态 |
| :--- | :--- | :--- | :--- |
| **`spine`** | 9 文件 / 1,479 行 | Lane/Worker 串行、OriginPools、抢占打断、Barrier 同步 | 🟡 核心跑通，待补齐 Barrier 与 Teardown 级联 |
| **`agent`** | 30 文件 / 7,463 行 | Subagent 层次体系、Tool 语义索引、MCP 协议、Ask User 阻断 | 🟡 基础 Loop 跑通，待扩展 Subagent 与完整内置工具 |
| **`context_engine`**| 16 文件 / 3,300 行 | Curator 决策器、两阶段装配流水线、Turn 摘要、原子裁剪 | 🟡 预算与闭包跑通，待完善分段 SegmentBuilders |
| **`providers`** | 12 文件 / 2,931 行 | 指数退避、跨模型自动 Fallback、Azure/Codex 专用适配器 | 🟡 LiteLLM 跑通，待补齐 Fallback 链与 OAuth Kit |
| **`routing`** | 10 文件 / 1,282 行 | KNN 语义模型路由、分类器特征抽取、复杂任务大模型分流 | ⚪ 待复刻 |
| **`call_efficiency`**| 9 文件 / 1,594 行 | Prompt 缓存对齐、模型目录静态缓存、动态定价与计费 | ⚪ 待复刻 |
| **`token_wise`** | 8 文件 / 676 行 | System 与 Tail 提示词缓存优化器 | ⚪ 待复刻 |
| **`sandbox`** | 9 文件 / 1,730 行 | Anthropic SRT 操作系统沙箱、BoxLite MicroVM、Debug Server | 🟡 Direct/Isolated 跑通，待接入 SRT / BoxLite |
| **`session`** | 3 文件 / 1,106 行 | 代际控制 (Storage Epoch)、跨进程文件锁、会话分叉与导出 | 🟡 基础存取跑通，待接入文件锁与 HTML/MD 导出 |
| **`channels`** | 23 文件 / 2,348 行 | 飞书、企微、QQ 机器人适配器、多媒体转码与流式推送 | ⚪ 待复刻 |
| **`tracing`** | 8 文件 / 1,879 行 | OpenTelemetry 语义约定、分布式 Span 收集、本地 Web 查看器 | ⚪ 待复刻 |
| **`memory_engine`** | 21 文件 / 4,500 行 | Skill Forge 动态铸造、长期记忆整理、记忆合流 (Fusion) | ⚪ 待复刻 |
| **`evolver`** | 63 文件 / 17,328 行 | 进化树、多臂老虎机 (Bandit)、Fisher 统计门禁、代码自改进 | ⚪ 待复刻（原工程最大模块） |
| **`proactive_engine`**| 5 文件 / 1,522 行 | Cron 定时任务、后台常驻触发器 | ⚪ 待复刻 |
| **`tui_rpc`** | 20 文件 / 5,015 行 | JSON-RPC 双向服务、确认代理 (ConfirmBroker)、问题代理 | ⚪ 待复刻 |
| **`ui-tui`** | 数十文件 / 数万行 TS | Node.js 22 + React + Ink 原生终端 UI | ⚪ 待复刻 |
| **`config`** | 8 文件 / 2,944 行 | 多 Provider 热重载、渠道授权持久化、Schema 校验 | 🟡 基础 settings 跑通，待补全动态热更 |
| **`cli`** | 33 文件 / 10,189 行 | 20+ 个生产级子命令组（gateway、cron、doctor、evolve 等） | 🟡 基础 run/chat/session 跑通，待完善矩阵 |
| **`auth & security`**| 7 文件 / 398 行 | 权能 Token (Capability Token)、白名单网络访问控制 | ⚪ 待复刻 |
| **`eval_engine`** | 14 文件 / 799 行 | 迭代前/后审计钩子 (Tool Audit Hook)、大模型裁判裁判器 | ⚪ 待复刻 |
| **`plugin`** | 7 文件 / 1,024 行 | 插件清单规范 (Manifest)、动态载入与隔离发现 | ⚪ 待复刻 |
| **`benchmarks`** | 6 大测试套件 | CodeFlowBench, AppWorld, PinchBench, ClawBench 等 | ⚪ 待复刻 |

---

## 2. 22 个子系统 1:1 详细功能矩阵与契约规范

### 2.1 Spine 并发调度与多会话管道 (`spine`)
- **文件清单**：
  - `_barrier.py`: 异步多任务完成屏障 (`finish_barrier`)。
  - `events.py`: 严格定义 `TurnEvent` = 生命周期事件 (`TurnStarted`, `TurnEnded`, `TurnFailed`) + 交付事件 (`TextDelta`, `ToolEvent`, `Notice`)。
  - `message.py`: 结构化输入入站载荷 `IntakeMessage`、`Media`、`Source`。
  - `pools.py`: `OriginPools` 互斥信号量（User Pool vs System Pool），彻底杜绝并发饥饿。
  - `runner.py`: `TurnRunner` 封装 Agent 实际执行与生命周期钩子派发。
  - `scheduler.py`: `Lane` / `Worker` 模型，`_inject_mailbox` 暂存机制，`BusyPolicy` (`APPEND`, `INTERRUPT`, `INJECT`)，空闲 Reaper 清理（默认 300s TTL）。
  - `teardown.py`: 四阶段关闭流程：Seal -> Drain -> Grace -> Cascade。
  - `turn.py`: `TurnRequest` (不可变 frozen dataclass)、`TurnHandle`。
- **1:1 复刻标准**：
  - 调度器完全接管所有生命周期状态与 Terminal Future 的 Resolve 唯一所有权；
  - 同一 Lane 内任务严格按顺序串行，跨 Lane 依据 OriginPools 并发。

### 2.2 Agent 运行时、子智能体与高级工具链 (`agent`)
- **文件清单与功能**：
  - `agent/loop/main.py`: AgentLoop 核心状态机，执行环境上下文组装与错误恢复。
  - `agent/loop/checkpoint.py`: 每轮执行生成快照，支持断点恢复。
  - `agent/loop/recovery.py`: 工具失败自动重试、上下文超限时自动压缩重试。
  - `agent/subagent/manager.py`: 派发子智能体执行子任务，支持隔离上下文与超时控制，结果作为系统事件注入主会话。
  - `agent/tools/`:
    - `base.py`: `Tool` 抽象基类、`ToolResult`（携带 `failed: bool` 状态）、`ToolRegistry`。
    - `filesystem.py`: 增强文件读写、行范围切片读取、原子追加。
    - `shell.py`: 命令行工具（与 Sandbox 深度联动）。
    - `web.py`: 网页抓取、HTML 清洗与 Readability 正文提取。
    - `file_search.py`: 本地文件全文检索与 glob 模式匹配。
    - `tool_search.py`: 动态工具语义检索，针对拥有几十个工具时按需加载。
    - `tool_index.py`: 基于内存向量与关键字的工具描述索引。
    - `mcp.py`: Model Context Protocol (MCP) 客户端集成，对接外部 MCP Server。
    - `ask_user.py`: 阻塞式人工交互工具（审批危险命令、参数澄清），带超时免中断标记 (`blocking_interaction=True`)。
    - `spawn.py`: 派生后台长任务命令。
    - `skill.py`: 动态加载并执行 Local Skill。
  - `agent/hook/`:
    - `base.py` & `composite.py`: 智能体执行前/后、工具调用前/后的复合钩子管道。
  - `agent/personalizer/`:
    - 针对用户风格与个性化偏好的动态 Prompt 注入。

### 2.3 Context Engine 分层上下文治理与装配 (`context_engine`)
- **装配管线架构**：
  - **Phase A (静态/独立分段)**：并行构建 `Identity` (身份定义)、`Bootstrap` (引导契约)、`Memory` (静态长期记忆)、`ActiveSkills` (激活技能)、`Skills` (候选技能列表)。
  - **Phase B (动态/历史分段)**：根据 Phase A 计算出的固定 Token 开销，计算剩余 Token 预算，驱动 `Curator` 与 `HistoryTrimmer`。
- **关键文件与算法**：
  - `assembler.py`: `ContextAssembler` 实现双阶段组装。
  - `history_trimmer.py`:
    - `canonical_ids`: 工具调用/结果双向传递闭包（严防悬空）。
    - `structural_errors`: 协议配对校验。
    - `compact_tool_results`: 历史旧工具输出折叠（保留首尾）。
    - `trim`: 按整轮 User 边界（Turn Groups）降级丢弃。
  - `curator.py`: 会话历史的语义级管理、目标跟踪与关键决策点保留。
  - `turn_summaries.py`: 对历史轮次生成带结构摘要，落盘存储在 `context_memory/`。
  - `segments/`: 9 个专门的 SegmentBuilder 类，严格按顺序渲染为 Markdown 章节。

### 2.4 Providers 多模型适配、容灾与 Fallback (`providers`)
- **企业级容灾特性**：
  - `base.py`: 定义 `ErrorClassification`（区分 `retryable` 重试当前模型、`should_fallback` 切换备用模型、`should_compress` 触顶压缩后重试）。
  - `litellm_provider.py`: 基础适配与标准转换。
  - `azure_openai_provider.py`: Azure 专属 API 版本、Deployment Name、Managed Identity 支持。
  - `openai_codex_provider.py`: GitHub Copilot / Codex OAuth 设备码登录流与 Token 刷新。
  - `transcription.py`: 语音转文本 Provider（用于语音输入渠道）。
  - `registry.py`: Provider 工厂与多模型单例注册中心。

### 2.5 Routing KNN 语义模型路由 (`routing`)
- **按难度动态派发模型**：
  - `knn_router.py`: 基于嵌入向量与余弦相似度的最近邻分类器。
  - `classifier.py`: 意图与任务复杂度评估器（简单问答派发给轻量/小模型，复杂编码与架构规划派发给顶配模型）。
  - `profiles.py`: 模型画像与性能/单价成本画像矩阵。
  - `generate_embeddings.py`: 离线/在线生成样本特征向量。

### 2.6 Call Efficiency & Token-Wise 提示词缓存与成本核算
- **大模型 Prompt Caching 优化**：
  - `system_and_tail_cache.py`:
    - **前缀静态对齐**：确保 System Prompt 与工具定义在多轮调用间字符完全一致，实现 100% 命中大模型前缀缓存（如 Claude / DeepSeek Cache）。
    - **尾部滑动缓存**：对最近几轮的历史上下文保持稳定结构。
  - `pricing.py`: 维护主流模型按每百万 Token 输入/输出/缓存命中的真实价格表。
  - `ledger.py` & `usage_tracker.py`: 记录每次调用的绝对财务成本并支持明细导出。

### 2.7 Sandbox 操作系统与微虚拟机级安全沙箱 (`sandbox`)
- **多层级沙箱方案**：
  - `direct_executor.py`: 宿主直接子进程执行（带工作目录与超时守护）。
  - `srt_executor.py`: **Anthropic SRT (Sandbox Runtime Toolkit)** 深度集成，使用 Linux Seccomp / Landlock / AppArmor 进行操作系统级强隔离。
  - `boxlite_executor.py`: **BoxLite MicroVM** 轻量虚拟机隔离，秒级拉起独立 Linux 微内核沙箱。
  - `debug_server.py`: 沙箱内调试命令与端口转发代理。

### 2.8 Session 工业级会话存取与代际控制 (`session`)
- **存储可靠性**：
  - `manager.py`:
    - **Storage Epoch**：基于纪元版本号的版本冲突检测，杜绝多进程并发覆盖；
    - **Locked Append**：跨平台文件锁（`portable_lock.py`）安全追加；
    - **Atomic IO**：临时文件写入 + 原子重命名（`atomic_replace`）。
  - `export.py`: 将 Session 导出为独立自包含的 HTML 格式报表或 Markdown 文档。

### 2.9 Channels 多平台消息网关 (飞书/企微/QQ) (`channels`)
- **IM 机器人支持**：
  - `manager.py` & `registry.py`: 统一的 Channel 注册管理。
  - `adapters/feishu/`: 飞书官方 Lark OAPI 对接，支持富文本卡片交互、图片收发与会话绑定。
  - `adapters/wecom/`: 企业微信机器人 SDK 封装。
  - `adapters/qq/`: QQ 开放平台机器人接口。
  - `media.py` & `transcribe.py`: 音视频流下载、缓存与自动语音转写。

### 2.10 Tracing OpenTelemetry 分布式链路追踪 (`tracing`)
- **可观测性**：
  - `semconv.py`: 符合 OpenTelemetry GenAI 规范的语义属性标准（`gen_ai.request.model`、`gen_ai.usage.prompt_tokens` 等）。
  - `spans.py` & `trace.py`: 分布式调用上下文传递与 Span 生命周期管理。
  - `store.py`: 本地 Trace 持久化存储。
  - `viewer/`: 内置本地静态网页查看器，可视化展示 Agent 调用瀑布流图。

### 2.11 Memory Engine 记忆提炼与 Skill Forge (`memory_engine`)
- **长期记忆体系**：
  - `consolidate/consolidator.py`: 对历史长对话进行自动化事实提取与提炼。
  - `skill_local/`: 本地文件技能 (`SKILL.md`) 监控器与动态池加载。
  - `skill_forge/`:
    - **Skill 自动铸造**：根据会话中解决复杂问题的过程，全自动提炼、测试并生成新的规范化 Skill 文件；
    - 包含 Gate 校验门禁、Router 路由、Fusion 融合与 Catalog 编目。

### 2.12 Evolver 技能自进化引擎 (`evolver`)
> **原工程最庞大子系统（17,328 行代码）**
- **自适应强化进化架构**：
  - `tree/`: 进化树节点状态存储、Git 分支隔离与回滚操作。
  - `orchestrator/`: 调度主循环、打分引擎、终止条件判断。
  - `orchestrator/gates/`: **Fisher 精确检验门禁**与成对统计显著性验证，确保只有统计上确实提高成功率的改动才被合并。
  - `orchestrator/nodes/`: 自动诊断 (Diagnose)、语义判别 (Semantic)、分类学编排 (Taxonomy)、候选设计 (Design)。
  - `scheduler/`: 树感知多臂老虎机 (`tree_aware_bandit.py`) 与冷启动探索策略。
  - `judge/`: 自动化裁判 LLM 接口与结构化解析。
  - `applier/`: 代码补丁应用与路径安全防护（Beacon Guard & Path Guard）。

### 2.13 Proactive Engine 定时任务调度器 (`proactive_engine`)
- **后台常驻服务**：
  - 基于 `croniter` 的标准 5 位 Cron 表达式解析器。
  - 定时触发新 Turn 并打上 `Origin.CRON` 标签提交给 Spine 调度器执行。

### 2.14 TUI RPC 跨语言双向通信总线 (`tui_rpc`)
- **与 Node.js 客户端的协议中枢**：
  - `server.py`: 基于 Stdio 或 Unix Domain Socket 的 JSON-RPC 2.0 异步服务端。
  - `dispatcher.py`: 方法调用分发器。
  - `subscriptions.py`: 主题发布/订阅流，实时推送 Token、Log、Tool 进度。
  - `confirm_broker.py` & `question_broker.py`: 阻断式用户提问与高危操作二次确认中继代理。
  - `methods/`: 覆盖 `turn`, `session`, `terminal`, `system`, `model`, `config` 等 10 大类 RPC 方法。

### 2.15 UI-TUI 原生终端交互前端 (`ui-tui`)
- **纯终端图形交互**：
  - 基于 Node.js 22、React、Ink 构建。
  - 实时 Markdown 流式高亮渲染、工具执行展开/折叠面板、会话列表侧边栏、成本图表渲染。

### 2.16 Config 动态配置与凭据热更新 (`config`)
- **配置治理**：
  - `schema.py`: Pydantic V2 完整强类型配置树。
  - `update_providers.py`: 动态通过命令行增删改大模型配置而无需手改 YAML。
  - `update_channels.py`: 渠道参数热更新。
  - `paths.py`: 跨平台运行时路径解析器。

### 2.17 CLI 完整生产级命令矩阵 (`cli`)
- **完整 Typer 命令行群组**：
  - `orangecode run`: 单次任务执行。
  - `orangecode chat`: 终端多轮交互。
  - `orangecode session`: 会话管理 (`list`, `show`, `delete`, `export`)。
  - `orangecode gateway`: 后台网关常驻启动 (`start`, `stop`, `status`)。
  - `orangecode cron`: 定时任务管理 (`add`, `list`, `remove`)。
  - `orangecode channel`: 消息渠道管理 (`feishu`, `wecom`, `qq`)。
  - `orangecode provider`: 大模型供应商配置矩阵管理。
  - `orangecode sandbox`: 沙箱探针自检与模式切换。
  - `orangecode skill`: 本地技能管理与测试。
  - `orangecode evolve`: 进化引擎启动与进化树查看。
  - `orangecode doctor`: 环境配置、网络连通性与 Python/Node 版本健康体检。
  - `orangecode tracing`: 链路追踪日志检索与本地 Web 仪表盘启动。

### 2.18 Auth & Security 权限令牌与安全边界 (`auth` & `security`)
- **受控访问体系**：
  - `capability_token.py`: 针对敏感工具执行的限时、限范围签发权能 Token。
  - `allowlist.py` & `network.py`: 出网白名单域名与安全代理过滤。

### 2.19 Eval Engine 评测运行时与审计钩子 (`eval_engine`)
- **合规审计与打分**：
  - 循环迭代前/后审计钩子 (`ToolAuditHook`)。
  - 任务完成度判决大模型提示词模板与自动打分适配器。

### 2.20 Plugin 插件生命周期与发现机制 (`plugin`)
- **插件扩展架构**：
  - 独立插件包清单 (`manifest.py`) 解析。
  - 插件发现、隔离上下文注入与动态生命周期卸载。

### 2.21 Benchmarks 标准基准评测套件 (`benchmarks`)
- **基准测试数据与 Runner**：
  - `codeflowbench`: 针对 Runtime、Context 治理与工具准确度的定制基准。
  - `pinchbench`, `appworld`, `clawbench`: 跨平台、长链条复合任务测试套件。

### 2.22 Templates & Onboarding 引导模板与契约文档
- **系统预设模板**：
  - `SOUL.md`: 智能体核心人格与行为边界。
  - `USER.md`: 用户画像与本地配置说明。
  - `TOOLS.md`: 工具声明契约。
  - `AGENTS.md`: 多 Agent 交互协议。

---

## 3. 1:1 全量复刻阶段实施里程碑

为了保证代码质量与功能零遗漏，整个复刻工程划分为 **6 大攻坚里程碑**，每个阶段均包含源码实现与独立单元测试覆盖：

```mermaid
flowchart LR
    M0["M0: 微内核跑通 (已完成)"] --> M1["M1: 完备工具与子智能体"]
    M1 --> M2["M2: 模型容灾、智能路由与缓存"]
    M2 --> M3["M3: 深度沙箱与生产级会话"]
    M3 --> M4["M4: 多渠道网关与常驻 Gateway"]
    M4 --> M5["M5: 记忆引擎与 Evolver 进化树"]
    M5 --> M6["M6: TUI 前端、RPC 与 Benchmark"]
```

### 里程碑规划排期：

- **Milestone 0: 微内核基座（已完成 ✅）**
  - 项目初始化、基础配置、LiteLLM 封装、AgentLoop 状态机、Spine 调度串行排队与打断、原子闭包与 BM25、基础 CLI、21 项测试通过。
- **Milestone 1: 丰富工具链与多智能体系统（立即启动 🚀）**
  - 交付物：`SubagentManager`、`WebTool`、`FileSearchTool`、`ToolSearch` 语义动态加载、`AskUserTool` 交互阻断、`MCP` Client。
- **Milestone 2: 模型层高可用、智能路由与缓存治理**
  - 交付物：`ErrorClassification`、跨模型 Fallback 降级链、KNN 语义模型路由、System/Tail Prompt Caching 优化器与定价账本。
- **Milestone 3: 深度安全沙箱与企业级会话存储**
  - 交付物：Anthropic SRT 沙箱接入配置、BoxLite MicroVM 适配器、跨进程文件锁 `StorageEpoch`、会话 HTML/Markdown 导出。
- **Milestone 4: 外部消息网关与后台常驻服务**
  - 交付物：飞书 (Lark)、企微 (WeCom) 适配器、多媒体转码、Cron 定时任务服务、Gateway 守护进程与文件锁。
- **Milestone 5: 记忆提炼与 Evolver 技能自进化系统**
  - 交付物：Skill Forge 自动铸造、长期记忆 Consolidator、Evolver 进化树、Fisher 统计检验门禁、Bandit 调度。
- **Milestone 6: 跨语言 TUI 交互界面、评测套件与完整 CLI 矩阵**
  - 交付物：JSON-RPC 2.0 服务端 (`tui_rpc`)、Node.js 22 + React + Ink TUI 前端、CodeFlowBench 评测套件、`orangecode doctor / evolve / cron` 等全量 CLI 命令。

---

## 4. 质量验收与对齐度校验契约

每个里程碑代码合并前，必须满足以下硬性指标：
1. **测试通过率 100%**：使用 `uv run pytest` 执行全量自动化测试，无任何 Skip/Fail。
2. **代码规范零警告**：使用 `uv run ruff check .` 执行静态分析，通过全部类型与格式检查。
3. **接口签名 1:1 对齐**：函数参数、返回值类型、异常定义与原项目保持严格兼容。
4. **Git 提交原子化**：每个子功能均有独立、清晰的 Commit 记录。
