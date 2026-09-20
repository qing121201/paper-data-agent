# 项目目录说明

## 会进入代码仓库的内容

| 路径 | 用途 |
|---|---|
| `paper_data_agent/` | 产品源码：桌面 UI、论文库、检索、阅读、LLM、工具和工作流 |
| `paper_data_agent/ui/` | 桌面端界面模块：主题、首页、论文库、Agent 对话和模型设置均已独立 |
| `paper_data_agent/tool_adapters/` | 受控外部工具适配器：在线检索、图表、导图和 PPT 分模块实现；旧 `adapters.py` 仅作兼容门面 |
| `paper_data_agent/retrieval/` | PDF/分块索引、BM25 与本地向量混合检索、检索评测 |
| `paper_data_agent/agent_tools/` | 提供给科研工作流的白名单论文工具和参数校验 |
| `paper_data_agent/research_workflow/` | LLM 规划循环、工具执行、工作流数据契约和用户文本规范化 |
| `tests/` | 自动回归测试，覆盖检索、推荐、导入、规划、全文阅读、PPT、图像与 GUI 关键逻辑 |
| `benchmarks/` | 10 条人工标注的检索查询，用来比较文件名基线和 BM25，不是训练集 |
| `config/README.md` | 本机 UI 配置格式说明；真正的 `config/ui.json` 不提交 |
| `docs/` | 架构、安装、Skill、安全边界和未来扩展说明 |
| `docs/decisions/` | 重要架构选择及其理由；用于避免后续 AI 反复推翻已确认方案 |
| `scripts/` | Windows 调试、PPT/导图等受控辅助脚本 |
| `third_party/` | 固定版本的第三方 Skill 资料、许可证和来源记录 |
| `libraries/README.md` | 论文库格式说明；真实论文和索引不提交 |
| `启动论文Agent.cmd` | Windows 一键启动入口 |

## 只保留在本机、不进入代码仓库的内容

| 路径 | 原因 |
|---|---|
| `.env` | 可能包含 API Key |
| `libraries/*` | 用户论文、网页下载、索引、会话和生成物，可能有版权或隐私信息 |
| `output/` | 旧实验结果和生成物 |
| `tmp/` | 浏览器、下载和渲染临时文件，体积大且可重新生成 |
| `科研实践报告/` | 个人报告、模板、成品和渲染检查材料 |
| `config/ui.json` | 本机皮肤等偏好 |
| `config/discovery.json`、`config/discovery_cache.json` | 本机论文订阅与当天推荐缓存 |
| `task_plan.md`、`progress.md`、`findings.md` | 本次开发过程记录，不是产品运行必需文件 |

`.git/` 是 Git 自己维护的版本历史和索引数据库，不是 Agent 功能代码。不要手动编辑或删除其中的文件；日常通过 `git status`、`git log`、`git commit` 操作。

每个真实论文库可以包含 `index.vectors.npz`（压缩向量）和 `index.vectors.json`（模型名、维度、chunk 指纹）。二者可重新生成，不提交到 GitHub。

## Benchmark 到底测什么

`benchmarks/retrieval_queries.json` 的每条记录包含一个查询和若干 `gold_title_contains` 标题片段。例如查询 “Agent Computer Interface、编辑文件命令” 时，把标题含 “SWE-agent” 的论文标作合理命中。评测只检查返回标题是否包含这些人工标注片段，并计算 Hit@1、Hit@K 和 MRR。

这不是给某个问题预先写死回答，也不会在正常对话中强制返回 SWE-agent；它只是开发者为了检查检索器有没有退化而建立的小型测试集。它不能证明综述写得好，也不能代替真实用户问题评测。

## 文件应该放在哪里

- 能被多个页面复用的产品逻辑放在 `paper_data_agent/` 的领域模块，不放进按钮回调。
- 只负责布局、控件和用户交互的代码放在 `paper_data_agent/ui/`。
- 对外部模型、OpenAlex、PowerPoint 或脚本的调用放在基础设施/工具适配层，不让业务层直接拼命令。
- 回归测试按能力放在 `tests/test_<能力>.py`；人工检索基准只放 `benchmarks/`。
- 用户论文、密钥、缓存和生成物属于运行时数据，不因为“整理目录”而移动到源码或提交 Git。
- 科研实践报告属于独立交付物，保留在 `科研实践报告/`，不与产品源码混放。
