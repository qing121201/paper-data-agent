# 项目目录说明

## 会进入代码仓库的内容

| 路径 | 用途 |
|---|---|
| `paper_data_agent/` | Agent 主程序：GUI、论文库、索引、阅读、LLM、工具和工作流 |
| `tests/` | 66 项自动回归测试，覆盖检索、导入、规划、全文阅读、PPT、图像与 GUI 关键逻辑 |
| `benchmarks/` | 10 条人工标注的检索查询，用来比较文件名基线和 BM25，不是训练集 |
| `config/README.md` | 本机 UI 配置格式说明；真正的 `config/ui.json` 不提交 |
| `docs/` | 架构、安装、Skill、安全边界和未来扩展说明 |
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
| `task_plan.md`、`progress.md`、`findings.md` | 本次开发过程记录，不是产品运行必需文件 |

`.git/` 是 Git 自己维护的版本历史和索引数据库，不是 Agent 功能代码。不要手动编辑或删除其中的文件；日常通过 `git status`、`git log`、`git commit` 操作。

每个真实论文库可以包含 `index.vectors.npz`（压缩向量）和 `index.vectors.json`（模型名、维度、chunk 指纹）。二者可重新生成，不提交到 GitHub。

## Benchmark 到底测什么

`benchmarks/retrieval_queries.json` 的每条记录包含一个查询和若干 `gold_title_contains` 标题片段。例如查询 “Agent Computer Interface、编辑文件命令” 时，把标题含 “SWE-agent” 的论文标作合理命中。评测只检查返回标题是否包含这些人工标注片段，并计算 Hit@1、Hit@K 和 MRR。

这不是给某个问题预先写死回答，也不会在正常对话中强制返回 SWE-agent；它只是开发者为了检查检索器有没有退化而建立的小型测试集。它不能证明综述写得好，也不能代替真实用户问题评测。
