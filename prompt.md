你现在是一个“研究工程一体化”的高级代码代理。你的唯一目标是：
基于本文件夹下的三份 deep-research-report，直接实现一个可运行、可复现实验结果、可产出图表与统计结论的小规模快速验证代码仓库。

/disk0/home/gaohaoyu/multi-agent-sys/deep-research-report.md是idea说明
/disk0/home/gaohaoyu/multi-agent-sys/deep-research-report-plan.md是初步的全流程实验计划
/disk0/home/gaohaoyu/multi-agent-sys/deep-research-report-minplan.md是最小规模快速验证实验计划

1、你需要在 mas 这个conda环境中进行实验，有什么需要的依赖包可以直接安装

你不是来讨论方案优劣的，你是来写代码的。
你必须先完整吸收三份 deep-research-report，再开始编码。

========================
一、你必须先理解的论文 idea
========================

这篇论文的核心 idea 是：

1. 研究对象不是静态路由，而是“动态 worker 池”下的能力感知协同调度。
2. 任务分布相对稳定，但 worker 会变化：模型、推理能力、成本、时延、参数配置、工具权限、版本等都可能变化。
3. 上层 controller / router 不能直接知道每个 worker 的真实能力边界，只能通过执行反馈逐步更新对每个 worker 的能力画像。
4. 每个 worker 不是一个单一标量分数，而是一个“多维能力嵌入/画像”，至少包含：
   - 任务适配性
   - 预期成功率
   - token 成本
   - latency
   - stability / 鲁棒性
5. router 根据任务表示 + 当前 worker 能力后验，决定：
   - 直接路由给某个 worker
   - 或在少量情况下进行轻量 decomposition，再路由
6. 目标是在 success / cost / latency / coordination overhead 之间做折中。
7. 小规模验证的核心目标不是做到最终 SOTA，而是要尽快、尽可能干净地回答：
   - 这个 idea 是否 work？
   - 相对 baseline 带来的提升幅度是多少？
   - 如果没有提升，失败原因是什么？

你写的代码必须服务于这个目标，而不是偏离成别的研究。

========================
二、你必须读取并继承的内容
========================

你必须读取三份 deep-research-report，并从中抽取以下内容用于实现：

A. related work positioning
B. 小规模快速验证 protocol
C. 4 个 OpenRouter worker 的选择与配置
D. benchmark 选择
E. baseline 设计
F. 核心图表
G. 统计检验
H. 失败分析路径

你不能忽略已经给出的实验计划。
你不能自行发明一套与既有计划不一致的新实验。

如果实验计划里已经给出伪代码、文件结构、超参数、日志字段、图表定义，你应优先落地这些内容。

========================
三、你要实现的实验目标（强约束）
========================

你要实现一个“小规模快速验证”实验，要求如下：

1. 总任务规模固定为 500。
2. 采用 4-worker 异质池，全部通过 OpenRouter API 调用。
3. 需要包含：
   - 我们的方法（capability-aware router）
   - baseline 1: random routing
   - baseline 2: cost-first routing
   - baseline 3: single-best routing
4. benchmark 采用：
   - GSM8K
   - HumanEval
5. 任务流构造：
   - 总共 500 个样本
   - HumanEval 全量 164
   - GSM8K 采样 336
   - 混合后打乱
   - 固定随机种子
6. 必须支持一次“动态扰动 / 漂移”：
   - 在 t = 250 左右触发
   - 不新增第 5 个 worker
   - 而是通过修改一个已有 worker 的参数或推理预算，模拟能力漂移/配置变化
7. 最终必须能得到可量化数字：
   - 各方法平均 success
   - 总 cost
   - 平均 latency
   - 相对 baseline 的提升幅度（绝对提升和相对提升都给）
8. 必须能产出核心图：
   - recovery curve（rolling success）
   - cost-quality scatter / Pareto style 图
   - baseline comparison bar chart
9. 必须能做统计检验：
   - paired bootstrap
   - McNemar
   - Wilcoxon（至少对 cost / latency）
10. 如果我们的方法没有正提升，代码和分析流程也必须能定位原因，而不是只输出一个空结果。

========================
四、固定的 worker 配置（不要改）
========================

采用以下四个 OpenRouter model id：

1. anthropic/claude-haiku-4.5
2. google/gemini-2.5-flash
3. deepseek/deepseek-r1-0528
4. qwen/qwen3-235b-a22b-2507

默认角色分工如下：

- claude-haiku-4.5: 高质量通用 worker
- gemini-2.5-flash: 长上下文 / 主力 worker
- deepseek-r1-0528: reasoning specialist
- qwen3-235b-a22b-2507: 低成本开源通用 worker

默认配置原则：

- temperature = 0.2
- top_p = 0.95
- 每题默认单样本
- 关闭工具
- GSM8K 输出格式强制为：FINAL: <number>
- HumanEval 只输出纯 Python 代码，不要 markdown，不要解释

reasoning 预算：
- Claude Haiku 4.5：中低 reasoning budget
- Gemini 2.5 Flash：low reasoning
- DeepSeek R1：reasoning enabled
- Qwen：默认不开 reasoning

注意：
你实现时要把 reasoning 相关参数写成容易修改的配置项，因为 OpenRouter / 模型接口可能变化。
但默认值必须和聊天历史中的实验方案尽量一致。

========================
五、router 的最小可运行实现（强约束）
========================

你实现的不是最终论文 full model，而是“小规模快速验证版”。

必须实现一个最小但合理的 capability-aware router，至少包含：

1. 任务表示
   至少包括：
   - task_type（gsm8k / humaneval）
   - prompt length
   - 简单结构特征
   - 可选：SBERT / sentence-transformers 语义向量

2. worker capability state
   每个 worker 至少维护：
   - success posterior on gsm8k
   - success posterior on humaneval
   - EMA cost
   - EMA latency
   - stability（最近窗口成功率波动）

3. online update
   每次任务执行后，必须更新对应 worker 的能力状态。

4. routing policy
   至少实现一个：
   - epsilon-greedy 或 UCB 风格的多目标打分策略
   score 至少考虑：
   - expected success
   - cost penalty
   - latency penalty
   - optional stability bonus

5. lightweight decomposition
   必须保留这个动作，但只允许是“轻量”
   即：
   - 仅在少量低置信度样本触发
   - 只增加 1 次 planner 调用
   - planner 输出短计划
   - 再把 plan 拼回原 prompt 做二次路由
   不能实现成复杂的多轮 agent tree search。

========================
六、baseline 的具体要求
========================

必须实现以下 baseline：

1. Random routing
   - 从 4 个 worker 中随机选 1 个

2. Cost-first routing
   - 优先选最便宜 worker
   - 可以保留一个极简的长上下文例外规则，但不要复杂化

3. Single-best routing
   - 固定只用一个较强通用 worker
   - 默认建议 gemini-2.5-flash
   - 但要把 fixed worker 设成配置项

========================
七、benchmark 与评测要求
========================

你必须直接实现：

A. 数据集下载与构造
- GSM8K：从 HuggingFace datasets 加载
- HumanEval：从 HuggingFace datasets 加载
- 固定 seed
- 生成混合任务流

B. GSM8K 自动判分
- gold 从答案中 “####” 后提取
- pred 优先匹配 `FINAL: <number>`
- 否则回退为提取最后一个数字
- 判分必须稳健处理逗号与格式细节

C. HumanEval 自动判分
- 读取 prompt / test / entry_point
- 在隔离环境中执行生成代码
- 跑 check(candidate)
- 要有 timeout
- 要记录 timeout / runtime error / wrong answer

D. 日志记录
至少记录：
- t
- task_id
- task_type
- method
- worker_id
- model_id
- request_id
- success
- failure_reason
- prompt_tokens
- completion_tokens
- total_tokens
- latency_ms
- cost_usd
- decomp_used
- decomp_request_id
- timestamp

E. 成本统计
- 优先使用 OpenRouter generation 级别 cost
- 如不可得，再 fallback 到 usage 估算
- 代码里要清晰区分“精确 cost”和“估算 cost”

========================
八、动态扰动设计（必须实现）
========================

你必须加入一次中途扰动，用于验证“动态 worker 池”叙事。

默认实现：
- 在 t == 250 时
- 对 deepseek/deepseek-r1-0528 做一次能力/配置漂移模拟
- 比如：
  - 降低 max_tokens
  - 或关闭 reasoning
  - 或二者同时进行
- 同时让 router 的 posterior update 增加轻微 forgetting，以更快适应

目的：
必须让实验能画出 recovery curve，而不是只有一个静态平均分。

========================
九、结果图与统计输出（必须有）
========================

你必须实现绘图代码，至少生成：

1. recovery_curve.png
   - x 轴：task index
   - y 轴：rolling success（建议窗口 50）
   - 画出 random / cost-first / single-best / ours
   - 标出 t=250 扰动点

2. cost_quality_pareto.png
   - x 轴：total cost
   - y 轴：average success
   - 4 个方法都画出来

3. baseline_compare.png
   - 显示 success / total cost / avg latency 的对比

并输出一个 summary 表：
- mean success
- total cost
- avg latency
- vs random 的 absolute / relative 提升
- vs cost-first 的 absolute / relative 提升
- vs single-best 的 absolute / relative 提升

必须输出成 CSV 和 markdown 两种形式。

========================
十、失败分析机制（必须实现）
========================

如果我们的 router 没有带来提升，或者甚至负提升，代码必须能帮助分析原因。

至少输出以下分析：

1. worker usage distribution
   - 各方法分别调用四个 worker 的比例

2. per-task-type performance
   - gsm8k / humaneval 分开统计
   - 看提升来自哪里，失败来自哪里

3. decomposition usage analysis
   - 触发率
   - 使用 decomposition 的样本 success/cost/latency

4. perturbation before/after comparison
   - t <= 250 与 t > 250 分开算
   - 检查恢复速度

5. error bucket
   - GSM8K: parse failure / wrong answer
   - HumanEval: timeout / runtime error / wrong answer

如果最终结果无效，你不能只说“没效果”。
你必须自动生成一个 failure_analysis.md，总结最可能的 3-5 个原因。

========================
十一、你要输出什么（最终交付物）
========================

你不能只输出“代码片段”。
你必须输出一个完整仓库的内容，按文件组织，至少包括：

- README.md
- requirements.txt
- .env.example
- configs/workers.yaml
- configs/experiment.yaml
- src/openrouter_client.py
- src/datasets.py
- src/eval_gsm8k.py
- src/eval_humaneval.py
- src/router.py
- src/baselines.py
- src/run_experiment.py
- src/plotting.py
- src/stats_tests.py
- src/analyze_failures.py

README 中必须包含：
- 环境安装步骤
- OpenRouter API key 配置
- 运行命令
- 结果输出位置
- 如何复现实验
- 如何切换是否启用 decomposition
- 如何切换扰动设置
- 如何切换 fixed single-best worker

========================
十二、代码风格要求（强约束）
========================

1. 必须写成可直接运行的 Python 项目。
2. 优先清晰、稳健、可复现，不追求过度抽象。
3. 每个文件要有明确职责。
4. 对所有关键函数写 docstring。
5. 对 API 调用加 retry/backoff。
6. 对异常情况有明确日志。
7. 不要省略 import。
8. 不要写伪代码占位；除非是极难确定的 OpenRouter 返回字段，你也要给出 fallback 实现。
9. 所有配置尽量外置到 yaml。
10. 不要写前端，不要写无关内容。

========================
十三、你的工作方式（非常重要）
========================

你必须按下面顺序输出：

Step 1. 先输出你从聊天历史三份 deep-research-report 中抽取出的“统一实验规格摘要”
- 不超过 80 行
- 用于证明你已经理解任务
- 不要重新发明方案

Step 2. 输出项目目录树

Step 3. 逐文件输出完整代码
- 每个文件都要完整
- 不要省略

Step 4. 输出运行命令
- 从安装到跑实验到画图到统计检验

Step 5. 输出“预期输出说明”
- 会产出哪些 csv / jsonl / png / md

Step 6. 输出“已知风险与后续增强点”
- 只列与本实验直接相关的

========================
十四、禁止事项
========================

1. 不要把任务改成别的数据集。
2. 不要把 500 改成别的规模。
3. 不要把 4-worker 改成别的 worker 池。
4. 不要擅自删除动态扰动。
5. 不要把 router 换成重型离线训练系统。
6. 不要把 decomposition 变成复杂多轮 agent 框架。
7. 不要只给 demo，不给完整仓库。
8. 不要忽略失败分析。
9. 不要写“这里省略实现”。
10. 不要先问我一堆澄清问题；默认按以上规范直接实现。

现在开始执行。