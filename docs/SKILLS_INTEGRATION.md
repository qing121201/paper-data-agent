# 科研 Skills 集成说明

## 已集成范围

项目固定引入 NatureSkills commit `9ea7330a17813a15421fe843778a776c258b9001` 的 11 个可调用 Skill，并引入 ai4s-skills commit `744ab2049a7b52ae726c43313468fd518b330980` 的 S1–S4，共 15 个可触发 Skill：

| Skill | 当前 Standalone Demo 能力 | 额外依赖边界 |
|---|---|---|
| nature-paper-card | 加载精读工作流，结合本地页码证据生成提示 | 实际生成需要 LLM |
| nature-ref-verifier | 加载参考文献核验工作流 | 在线多源核验需要外部数据库或网络 |
| nature-writing | 基于检索证据起草学术文本 | 实际生成需要 LLM |
| nature-reviewer | 对输入文本执行审稿工作流 | 实际生成需要 LLM |
| nature-polishing | 对输入文本执行润色工作流 | 实际生成需要 LLM |
| nature-reader | 执行论文阅读/对照解释工作流 | 完整图表与公式抽取需要相应脚本依赖 |
| nature-statistics | 执行统计报告审查工作流 | 新统计计算必须提供原始数据并接入计算工具 |
| nature-academic-search | 执行检索策略；`online_search` 已接 OpenAlex | 其他数据库仍需各自接口 |
| nature-figure | 执行科研绘图需求分析；CSV/TSV 可生成 PNG/PDF | Excel、R 和复杂多面板图仍需扩展 |
| nature-paper2ppt | 执行论文汇报结构并生成可编辑 PPTX | 依赖本机 Microsoft PowerPoint |
| nature-image2ppt | 执行图片型幻灯片重建工作流 | 对象级 PPTX 重建需专用 CLI 与视觉依赖 |
| research-explorer (S1) | 研究方向与选题空间探索 | 生成内容需要 LLM；在线证据可调用 OpenAlex |
| experiment-suite (S2) | 设计实验包、数据契约、结果与图表规范 | 任意实验代码不会被自动无审查执行 |
| integrity-auditor (S3) | 按图片、数值、逻辑和证据等级开展完整性审计 | 深度图片取证仍需专项视觉工具 |
| mindmap-render (S4) | 从论文证据或 Markdown 生成 HTML、PNG、PDF 思维导图 | 依赖 Playwright 与 Chromium |

## 运行机制

1. `SkillCatalog` 读取完整 `SKILL.md`、manifest 和其中可安全解析的 Markdown 引用。
2. 相对引用必须仍位于对应的 `third_party/nature_skills` 或 `third_party/ai4s_skills` 根目录内，路径越界会被拒绝。
3. 对话模式在每个步骤用受限 JSON 选择工具、检索词和 Skill；程序校验后执行，再把实际结果交回模型决定下一步。
4. `apply_skill` 可用写作 Skill 生成草稿，再由审查 Skill 处理这份草稿；中间产物标为模型生成，原始证据始终保留。达到 `finish` 或最终文件工具才完成本轮。原 CLI 仍保留关键词路由和 `--skill` 显式指定，供可复现实验使用。
5. LLM 只生成规划 JSON 与最终文本，不拥有终端或任意文件执行权限；第三方 Skill 中的命令不会被自动执行。

对话模式可选择 `clarify`、`search_papers`、`build_brief`、`survey_corpus`、`read_pages`、`read_full_papers`、`online_search`、`search_and_import`、`create_scientific_figure`、`create_presentation`、`create_mindmap`，并用 `apply_skill` 做中间分析、`finish` 结束本轮。中文任务由规划模型转换为更可能出现在英文论文中的检索词，避免直接用“写综述”等宽泛中文字符串检索英文正文。

证据读取采用可审计的完整单元：`survey_corpus` 为每篇选择完整摘要或明确标注的完整首页/前两页，`build_brief` 读取检索命中的完整 PDF 页；二者都先报告预算、实际覆盖和跳过项。`online_search` 对综述类任务可规划 2–4 个独立查询，结果会注明命中查询和“候选集并非领域总量”的边界。

默认最多加载 120,000 个 Skill 字符，以容纳 writing/polishing 的共享参考层。兼容模型的上下文窗口较小时，可用 `--max-skill-chars` 下调；被省略的参考文件会明确列在 `omitted_files`，不会悄悄假装已加载。

## API 协议

- `responses`：调用 `{base_url}/responses`，适合 OpenAI 官方 Responses API。
- `chat_completions`：调用 `{base_url}/chat/completions`，适合常见兼容服务。
- `auto`：`api.openai.com` 自动选择 Responses，其他地址选择 Chat Completions。

模型配置可从环境变量读取，也可在一键启动界面中输入。界面使用隐藏输入；用户可选择仅在本次进程使用，或明确选择保存到本机 `.env`。`.env` 已被 Git 忽略，但仍属于明文凭据文件，不应发送给他人。程序不会在异常信息或输出文件中主动打印请求头或 API Key。

## 第三方代码

NatureSkills 位于 `third_party/nature_skills`，S1–S4 位于 `third_party/ai4s_skills`。来源、固定版本和许可证分别见各目录的 `UPSTREAM.md` 与 `LICENSE`。本项目主要在外层增加安全加载、路由、证据拼装和受控执行适配器；另对 NatureSkills 的 OpenAlex 脚本做了一处有记录的本地补丁，移除 500 字符摘要硬截断，详见其 `UPSTREAM.md`。
