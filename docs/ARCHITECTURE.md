# 论文 Data Agent 结构说明

## 用户流程

1. `启动论文Agent.cmd` 启动 `paper_data_agent.gui`，默认进入一级“首页”。
2. 一级导航包含“首页 / 我的论文库 / 使用说明”；论文导入、Agent 对话和 PPT 是“我的论文库”内部的二级功能。
3. 首页加载本地订阅和当天缓存，并在有订阅时后台刷新 OpenAlex 推荐；热门方向点击后直接切换，连续点击只保留最后一个待刷新方向。推荐刷新使用独立状态，不阻塞 Agent 对话，并把公开全文加入指定论文库。
   首页内容位于自适应纵向滚动画布中，推荐表另有独立横向滚动，避免低高度或窄窗口裁掉论文操作区。
4. 用户新建或切换一个独立论文库。
5. 用户粘贴本地文件夹地址、使用 Windows 文件夹选择器，或输入公开论文网址。
6. `PaperLibrary` 保存来源元数据，调用 `PaperIndex` 解析 PDF、按页分块并建立索引。
7. 用户在聊天页提出任务；`ResearchWorkflowAgent` 让模型选择下一个受限工具、英文检索词和科研 Skill。
8. `_collect_steps` 执行并保存完整结果，再交给模型决定是否补读、补搜、执行写作/审查 Skill 或结束；每轮最多 6 个中间步骤。
9. 中间模型产物明确标记为非原始证据；`finish` 或文件工具结束本轮。GUI 通过线程安全回调逐步展示实际动作，异常检查点保留已完成步骤和证据。

## 代码职责

| 文件 | 职责 |
|---|---|
| `gui.py` | Windows 主窗口组装、论文库切换、导入、模型设置和聊天交互；后续页面继续从这里小步拆出 |
| `ui/theme.py` | 皮肤配色、Tk/ttk 样式和主题持久化；不包含论文或 Agent 业务逻辑 |
| `library.py` | 独立论文库目录、元数据、去重、索引更新和来源管理 |
| `discovery.py` | 首页订阅、OpenAlex 候选聚合、时间/引用/相关性排序与当天缓存 |
| `web_sources.py` | 公开 URL/失效页面校验、HTML 中 PDF 发现、下载限制和缓存 |
| `core.py` | PDF 抽取、文本分块、BM25/向量混合排序与受控工具注册 |
| `embeddings.py` | 公开本地 Embedding 模型、向量 sidecar、指纹校验和自动回退 |
| `reading.py` | 重建完整 PDF 页、识别完整摘要边界、制定不可拆分的证据预算计划 |
| `adapters.py` | OpenAlex、科研绘图、PowerPoint 和思维导图执行适配器 |
| `workflow.py` | 有界多步规划、工具执行、Skill 中间分析、检查点恢复和最终回答 |
| `skills.py` | NatureSkills/ai4s-skills 发现、路径边界和声明式规则加载 |
| `llm.py` | Responses 与 Chat Completions HTTP 客户端 |
| `config.py` | 模型配置的读取、校验、进程应用与可选本机保存 |
| `cli.py` | 供测试和实验复现使用的命令行入口 |
| `app.py` | 旧的文字菜单入口，保留作无 GUI 后备和调试用途 |

主启动器使用 `pythonw.exe`，因此双击时只显示图形窗口。若需要查看 Python 异常和调试输出，可运行 `scripts/启动GUI调试版.cmd`。

## 数据边界

- 本地 PDF 只读取，不复制、不修改。
- 网页 PDF 缓存到当前论文库的 `downloaded_papers`。
- 网页记录同时保留用户输入的网址和最终 PDF 地址。
- 只允许 HTTP/HTTPS 公开地址；本机、局域网、凭据型 URL 被拒绝。
- 登录、付费墙、验证码和反自动访问限制不会被绕过。
- `.env` 可能包含用户主动保存的明文 API Key，已被 Git 忽略，不进入对话记录。
- `config/discovery.json` 和 `config/discovery_cache.json` 保存本机订阅与当天推荐，已被 Git 忽略；不含 API Key。
- 向量索引保存为 `index.vectors.npz/json`，只含本地生成的数值向量和模型/指纹元数据；模型权重由 Hugging Face 缓存管理。

## Agent 可选择的工具

- `clarify`：对综述、全库脉络等范围或阅读深度不明确的任务先给出方案并等待用户确认。
- `search_papers`：针对明确问题定位少量最相关论文片段，供后续选页使用。
- `build_brief`：每篇保留一个最高相关命中页，读取完整 PDF 页并形成带路径、页码、预算和覆盖清单的证据包。
- `survey_corpus`：按证据预算为每篇读取完整摘要；识别失败时改读完整首页/前两页并明确标注。
- `read_pages`：按精确标题和物理页码读取完整页面，每次最多 12 页；未索引页面明确报告未读取。
- `read_full_papers`：按精确标题完整读取 1–5 篇论文的全部可提取文本页；预算不足时整篇留到下一批。
- `apply_skill`：按所选 Skill 对原始证据/前序草稿实际调用模型，保存带标签的中间工作。
- `finish`：结束收集与分析阶段，生成最终回答。
- `online_search`：通过 1–4 个 OpenAlex 查询检索公开元数据和完整索引摘要，去重后明确标注候选集边界。
- `search_and_import`：扩大候选池后按相关性和被引量尝试下载公开全文，持续补位到达到目标数量或候选耗尽。
- `create_scientific_figure`：把 CSV/TSV 数据生成 PNG/PDF 科研图。
- `create_presentation`：调用本机 PowerPoint 生成可编辑 PPTX，并运行结构质检。
- `create_mindmap`：把模型整理的论文大纲或用户 Markdown 渲染为 HTML/PNG/PDF。
- `none`：问候或不需要论文库的对话不调用本地检索。

工具名、Skill 名和规划 JSON 都经过白名单校验。模型不能凭规划结果任意执行终端命令或第三方 Skill 脚本。

## 当前没有的基础设施

当前版本没有自训练语言模型、独立向量数据库、自训练 Embedding、REST 服务或 SQL/云数据库。检索默认使用本地 BM25，可由用户建立 `multilingual-e5-small` 本地向量 sidecar，与 BM25 通过倒数排名融合；论文库、正文索引和会话仍使用 JSON/NPZ 文件。生成式模型通过 OpenAI 兼容 HTTP 接口调用。可选扩展及其成本见 [ARCHITECTURE_OPTIONS.md](ARCHITECTURE_OPTIONS.md)。

## 产品化架构原则

当前选择是“模块化桌面单体”：用户仍只启动一个桌面程序，但源码按产品能力划分模块。这样既不引入服务器、账号系统和部署成本，也能让界面、论文库、Agent、在线推荐和 PPT 分别演进。

依赖方向统一为：`UI -> 应用工作流 -> 领域能力 -> 基础设施`。例如首页可以调用论文发现服务，但论文发现服务不能反向导入 Tk 界面；Agent 可以通过工具接口读取论文库，但论文库不能依赖 Agent 的提示词。详细约束见 [MODULE_CONTRACTS.md](MODULE_CONTRACTS.md)，分阶段拆分顺序见 [REFACTORING_ROADMAP.md](REFACTORING_ROADMAP.md)。
