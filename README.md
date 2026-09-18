# Paper Data Agent

这是一个不绑定固定语料的本地论文 Data Agent Demo。用户可以为不同课题建立独立论文库，从任意本地文件夹或公开论文网址导入 PDF，然后直接与 Agent 对话。Agent 会自行选择本地论文工具、检索词和 NatureSkill，并返回可追溯到文件页码或原始网址的回答。

## 功能

- 新建、打开和切换多个独立论文库。
- 首页可按标签、期刊或会议订阅近期论文，每次推荐 3–5 篇，支持综合、最新、引用量和相关性排序，并可一键加入指定论文库。
- 通过粘贴路径或 Windows 文件夹选择器递归导入本地 PDF。
- 读取公开 PDF 直链或论文网页，自动发现 PDF、下载、缓存和去重。
- 按页分块建立 BM25 全文索引；可选下载公开多语言 Embedding 模型，建立本地向量 sidecar 并进行混合检索。
- 通过统一工具注册表调用检索、全文阅读、联网导入、写作审查和文件生成工具。
- 返回论文标题、绝对路径、页码、相关性分数和证据原文。
- 使用标注查询比较文件名匹配基线与全文 BM25 检索。
- 发现并安全加载 11 个 NatureSkills 与 4 个 ai4s 科研 Skills，不执行 Skill 文本中的任意命令。
- 根据任务自动选择 Skill，组合本地证据后调用在线或本地兼容模型。
- 可由 Agent 调用 OpenAlex 在线检索、CSV/TSV 科研绘图、可编辑 PPTX 和 HTML/PNG/PDF 思维导图工具。
- 提供 Windows 图形窗口、国内外常用模型预设、连接测试、四套皮肤和连续对话记录。
- 对综述、全库脉络等高投入任务先讨论阅读深度和范围，确认后再执行。

## 运行环境

- Python 3.10 或更高版本
- Python 依赖见 `requirements.txt`；PDF 解析可使用 pypdf 或 PyMuPDF 后备
- PPTX 生成需要 Windows 上的 Microsoft PowerPoint；思维导图截图需要 Playwright 浏览器
- 测试使用 Python 标准库 `unittest`

完整安装方法、可选系统依赖和测试命令见 [docs/INSTALLATION.md](docs/INSTALLATION.md)。目录用途和哪些内容不会提交见 [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md)。

## 快速运行

### 最简单的方式（推荐）

直接双击项目根目录中的 `启动论文Agent.cmd`。程序会自动进入正确目录并打开“论文 Data Agent”图形窗口；不需要 PowerShell 命令。

首次使用按下面操作：

1. 在“首页 · 今日论文”点击“订阅设置”，填写关注的标签、期刊或会议；启动时会刷新当天推荐，也可手动刷新。
2. 点击“新建论文库”，输入当前课题名称。
3. 在“论文导入”页粘贴本地文件夹地址，或点击“浏览选择”。
4. 也可以粘贴公开 PDF 或论文网页网址，点击“读取并加入论文库”。
5. 点击右上角“模型设置”，选择 DeepSeek、Kimi、千问、智谱等服务商并填写该平台的 API Key；点击“测试连接”。
6. 进入“与 Agent 对话”，直接输入任务，不需要自己选择工具或 Skill。

例如可以直接问：`这个论文库主要在讲什么？`、`精读 SWE-agent 并整理证据卡`、`基于当前论文库帮我写相关工作`、`在线查找 SWE-agent 的后续研究`、`在线搜索虚拟细胞相关论文并直接加入论文库`、`把当前论文脉络做成思维导图`。Agent 会自行选择检索、全库分析、在线搜索、公开 PDF 导入、科研绘图、PPT 或思维导图工具，并搭配一个科研 Skill，再执行并显示行动记录。空论文库也可以先在“与 Agent 对话”中使用“搜索并导入”场景。

每个论文库的数据结构和代码职责见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。本地论文不会复制；网页论文会缓存在对应论文库的 `downloaded_papers` 中。本地向量混合检索已经可用；REST、云同步和微调等尚未实现的选项见 [docs/ARCHITECTURE_OPTIONS.md](docs/ARCHITECTURE_OPTIONS.md)，不要把路线图当作现有能力。

### 今日论文与每日推送

首页订阅使用 OpenAlex 的公开元数据。程序会先扩大候选范围，再按订阅条件去重和筛选，只展示 3–5 篇；不会把“目标 5 篇”误当成“只检索 5 篇”。列表同时显示真实发表日期、期刊/会议、OpenAlex 引用数和公开全文状态。综合排序分别计算主题命中、新近程度和候选集内的引用得分，不把三者混成一个无法解释的数字；也可以单独按最新、引用量或相关性排序。

选择推荐论文和目标论文库后，点击“加入选中的论文”，程序会下载公开全文、建立全文索引并按 DOI、标题和文件哈希去重。只有元数据或受付费墙/登录限制的论文仍可打开来源，但不会伪装成已经导入。订阅和当天缓存保存在本机 `config/discovery.json` 与 `config/discovery_cache.json`，不会提交 Git。

当前“每日”含义是：应用启动时自动刷新当天结果，也可以手动刷新；没有在应用关闭后继续运行的后台定时任务和系统通知。若近期窗口不足 3 篇，会从同一年度候选池补足，并在列表保留真实日期，用户仍可看出哪些论文超出原窗口。

### 本地向量检索

在“论文导入”页点击“建立/更新向量索引”。首次使用会下载公开的 `intfloat/multilingual-e5-small`（模型权重约 471 MB），之后在本机生成 384 维向量。向量文件保存在当前论文库旁边，不进入 Git；检索自动使用 BM25 与向量倒数排名融合。论文发生增删后，界面会显示“向量需更新”，更新前自动回退纯 BM25。

也可以用命令行建立：

```powershell
python -m paper_data_agent.cli vectors --index "libraries\论文库名\index.json"
```

Embedding 过程在本机执行，不会因为建立向量而把论文发送给 Hugging Face；只有首次下载模型文件需要联网。

### 模型服务与皮肤

“模型设置”目前内置以下可编辑预设：DeepSeek、Kimi（Moonshot）、通义千问（阿里云百炼）、智谱 GLM、火山方舟（豆包）、硅基流动、OpenAI、Ollama（本机）和自定义 OpenAI 兼容接口。选择预设只会自动填写 Base URL、建议模型和协议；这些字段都能手动修改。服务商升级模型后，以其控制台中实际可用的模型 ID 为准。

“模型 ID”是可编辑下拉框，不是填写“4.1”这种简称，而要填写服务商控制台实际提供的完整 ID。界面预设只是便捷默认值；服务商升级或下线模型后，应以当前控制台和官方文档为准，也可以直接粘贴其他兼容模型 ID。

DeepSeek 默认开启思考模式，思维内容与最终回答分开返回。本 Demo 的规划和最终论文回答均保留 `high` 思考强度。`单次最大输出 token` 可以填写 1–393216，也可以留空或填写“自动”；自动模式下由服务商使用自己的默认值，DeepSeek 思考模式当前默认 64K。这个值是回答长度上限，不是论文输入上限；若服务端以 `finish_reason=length` 截断已有正文，程序会从截断处最多自动续写两次，连续三次仍超限时会明确标注内容可能不完整。

切换服务商时，输入框中的旧 API Key 会自动清空，避免误发给另一个服务。勾选保存后，密钥仅写入项目根目录的 `.env`；该文件已被 `.gitignore` 排除。点击“测试连接”会向所选模型发送一条很短的真实请求，可能产生极少量 API 用量。

顶部“皮肤”可以切换 `原始浅色`、`学术蓝`、`纸张暖色` 和 `深色夜读`。选择保存在 `config/ui.json`，下次启动自动恢复；它不包含密钥。

刚才出现的 `No module named paper_data_agent` 是因为 PowerShell 当时位于 `C:\Users\Administrator`，而不是本项目目录，并不表示 Agent 代码缺失。

### 命令行方式

如果使用 PowerShell，请先进入项目目录：

```powershell
cd "C:\Users\Administrator\Documents\ChatGPT\科研实践"
```

```powershell
python -m paper_data_agent.cli index `
  --input "D:\大三下课程\科研实践\论文已阅" `
  --output "output\paper_index.json"

python -m paper_data_agent.cli search `
  --index "output\paper_index.json" `
  --query "long horizon software evolution" `
  --top-k 3

python -m paper_data_agent.cli brief `
  --index "output\paper_index.json" `
  --query "How are software engineering agents evaluated?" `
  --output "output\evidence_brief.md"

python -m paper_data_agent.cli evaluate `
  --index "output\paper_index.json" `
  --benchmark "benchmarks\retrieval_queries.json" `
  --output "output\evaluation.json"
```

## 科研 Skills、执行工具与 LLM

列出已集成 Skill：

```powershell
python -m paper_data_agent.cli skills
```

先用 dry-run 检查路由、检索证据和将要发送给模型的提示，不需要 API Key：

```powershell
python -m paper_data_agent.cli agent `
  --index "output\paper_index.json" `
  --query "精读 SWE-agent 并生成结构化证据卡" `
  --dry-run `
  --output "output\skill_dry_run.md"
```

在线运行前，在当前 PowerShell 会话设置环境变量。不要把真实密钥写进 `.env.example` 或提交到仓库：

```powershell
$env:PAPER_AGENT_BASE_URL = "https://api.openai.com/v1"
$env:PAPER_AGENT_API_KEY = "你的 API Key"
$env:PAPER_AGENT_MODEL = "你有权访问的模型 ID"
$env:PAPER_AGENT_API_STYLE = "responses"

python -m paper_data_agent.cli agent `
  --index "output\paper_index.json" `
  --query "精读 SWE-agent 并生成结构化证据卡" `
  --output "output\paper_card.md"
```

若使用 Ollama、vLLM 或其他 OpenAI-compatible 服务，把 `PAPER_AGENT_BASE_URL` 改成服务提供的 `/v1` 地址，并设置 `PAPER_AGENT_API_STYLE=chat_completions`。模型名称和 API Key 要遵循该服务的配置。

日常使用不需要手动设置这些环境变量：一键启动界面中的“配置大模型 API”会完成同样的配置。本节命令主要供调试和实验复现使用。

也可以通过 `--skill nature-writing` 等参数跳过自动路由。完整集成范围、执行边界和第三方来源见 [docs/SKILLS_INTEGRATION.md](docs/SKILLS_INTEGRATION.md)。

## 输出解释

生成 PPT 后会切换到“PPT 预览与修改”。左侧选页，中间查看实际 PPTX 导出的预览，在下方输入针对该页的修改要求。修改保存为新版本，顶部可切换历史版本，旧版不会覆盖。目前逐页对话支持标题、正文和来源说明；换图、图表重绘及复杂布局编辑尚未接入。该入口管理本 Agent 生成且保留 `presentation_spec.json` 的文稿，不会直接改写同学提供的参考文件。

聊天页右上角显示当前任务阶段及论文证据准备数量。进度条表示阶段推进，不代表模型已完成思考的百分比；等待模型回答时会停留在当前阶段。导图的阅读覆盖说明放在聊天回答中，导图只呈现研究内容。点击“清空当前对话”会重置当前库的聊天上下文，旧会话归档至 `sessions/archive`，论文和生成文件保留。

检索结果中的 `page` 是 PDF 的物理页码。针对全库问题，Agent 会先按论文数和证据预算制定计划：优先为每篇读取一份边界可识别的完整摘要；无法可靠识别摘要边界时，改读完整首页/前两页并明确标注。针对聚焦问题，先检索相关论文，再读取命中 PDF 的完整页面。预算不足时只会跳过整个阅读单元，不会把摘要或页面从中间截断。

每次证据包都会列出论文总数、实际读取数、阅读范围、完整性、选择原因、估算 token 和未覆盖项。这里的证据 token 预算用于控制一次交给模型的论文文本量，不是 API 余额，也不是最终回答长度。简报不会把生成文字伪装成论文原文；正式写作前仍应打开对应页面核对上下文。

在线检索会展示实际使用的 1–4 个查询词，并合并去重候选论文。界面中的“得到 N 篇”只表示这些查询各自 Top-N 结果的候选集合，不表示整个研究领域只有 N 篇。在线阶段目前阅读 OpenAlex 元数据和其提供的完整索引摘要；只有将公开 PDF 导入论文库后，才会读取全文页面。

## Skill 和工具的区别

Skill 是一套“怎么做”的科研工作流说明，例如证据卡应该有哪些字段、审稿时应检查哪些风险、实验包怎样组织。工具是“真的去执行”的程序接口，例如检索 OpenAlex、读取本地索引、把 CSV 绘成 PNG/PDF、调用 PowerPoint 生成 PPTX。Agent 先用 LLM 判断任务，再选 Skill 规定方法、选工具完成动作；只有 Skill 而没有适配器时，模型只能给建议，不能产出真实文件。

当前动作包括：`clarify`（先讨论并等待确认）、`search_papers`、`build_brief`、`survey_corpus`、`read_pages`、`read_full_papers`、`online_search`、`search_and_import`、`create_scientific_figure`、`create_presentation`、`create_mindmap`、`apply_skill`、`finish` 和 `none`。其中 `search_papers`/`build_brief` 会在向量 sidecar 可用时自动使用 BM25+向量混合检索；`apply_skill` 会用指定 Skill 分析已有证据或审查上一份草稿；`search_and_import` 会检索 OpenAlex 并尝试把可公开下载的论文加入当前库。

## PPT 原图与自绘图（2026-09-16 更新）

在“PPT 预览与修改”中选中内容页，可要求“截取 SWE-bench 的方法原图，左文右图”或“根据这一页自绘三步流程图”。新版从当前论文库选取带图表的 PDF 页面，把图片和页面文字交给已配置的模型，按模型选择裁剪、插图、保存新版并导出预览。模型必须支持图片输入；仅支持文字的 API 不能自动看图裁剪。

支持图左文右、图右文左、图上文下和双图布局。原图标注论文名和物理 PDF 页码；自绘支持 2–6 步流程图、柱状图、折线图，必须附来源。数据图数值仍需核对原文，不得将不同评测条件直接混为排名。已有 CSV/TSV 绘图工具可先运行再交给 PPT 生成步骤使用。不含文生图模型服务，不用生成图片伪造实验结果。

每次编辑保存独立版本：`outputs/<版本>/assets/` 存放嵌入 PPT 的图片，`presentation_spec.json` 保留来源、裁剪坐标或绘图参数，`preview/` 保存实际 PPT 导出预览；`outputs/visual_assets/` 是素材缓存，`outputs/edit_proposals/` 保留模型修改提案以便排错。封面暂仅支持标题和副标题修改，内容页支持图文编辑。自绘图额外保存 SVG 与参数 JSON，PPT 内插入的是 PNG，并非图中每个元素都可单独编辑。

旧窗口需要关闭后重新运行“启动论文Agent.cmd”才会加载新代码。原文 PDF、旧 PPT 版本及科研实践报告不会被覆盖。

## 项目边界

当前版本采用“规划下一步 → 执行 → 检查实际结果 → 再规划”的循环。模型可先概览论文、按具体页码补读、调用写作 Skill 起草、调用审查 Skill 检查，再生成回答或文件。每轮最多 6 个中间步骤加一个结束步骤，避免无限调用；重复动作和累计超过 40 万字符的证据会暂停并保存完整进度。输入“继续上次任务”会带入已保存证据。步骤数上限是本地保护，具体模型仍有自身上下文上限。

在线检索当前使用 OpenAlex；要求“搜索并导入”时会尝试下载检索结果提供的公开 PDF，并逐篇报告候选数、公开地址数、成功导入数和失败原因。程序不绕过付费墙、登录或验证码。科研绘图支持 CSV/TSV；PPT 依赖本机 Microsoft PowerPoint；思维导图依赖 Playwright，缺少配套浏览器时尝试本机 Edge/Chrome。图片型 PPT 的对象级重建、任意 Excel/R 数据分析、多个付费学术数据库仍需要后续专用适配器。

## 为什么不需要训练

这个项目中的 Agent 不是一个新训练的语言模型，而是一套“工作流程序”：它负责检索论文、选择工具、组织证据、加载科研 Skill，并把需要理解和写作的部分交给现成的大模型。建立 BM25 论文索引属于数据预处理，不会更新任何模型参数。

原版 SWE-agent 的关键贡献同样主要是 Agent-Computer Interface（让通用语言模型以更合适的命令浏览仓库、编辑代码和运行测试），并使用 SWE-bench 做评测；它并不是把 SWE-bench 当训练集训练出一个独立小模型。后续确实出现了在软件工程轨迹上微调或强化学习的专用模型，但那是另一条技术路线。

因此，本 Demo 的离线检索不需要模型；要生成自然语言综述、精读卡片和审稿意见，则需要某个已经训练好的大模型进行推理。它可以是在线 API，也可以是本机 Ollama/vLLM 模型；使用本地模型时不需要云 API Key，但仍然需要下载并运行模型。
