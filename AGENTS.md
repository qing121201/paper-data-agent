# 论文 Data Agent：AI 开发规则

本文件适用于整个仓库。任何 AI 开发任务开始前，先阅读：

1. `docs/PRODUCT.md`：产品目标与非目标。
2. `docs/ARCHITECTURE.md`：运行流程、模块和依赖方向。
3. `docs/AI_WORKSTREAMS.md`：六个开发任务的职责与文件所有权。
4. `docs/MODULE_CONTRACTS.md`：跨模块接口及禁止耦合事项。

## 共同规则

- 本仓库采用“模块化单体”，不是把每个功能做成独立服务。
- 一个任务只修改自己拥有的模块；跨模块改动先在“产品架构与集成”任务确认接口。
- `gui.py`、`adapters.py` 是过渡兼容入口，不再继续堆入大段新逻辑。
- 用户论文、API Key、聊天记录和生成物不属于源码，禁止提交到 Git。
- 未经用户明确确认，不移动或删除 `libraries/`、`.env`、`科研实践报告/`。
- 不绕过登录、付费墙、验证码、网站权限或本机安全边界。
- 不允许模型生成任意命令并直接执行；工具必须经过白名单、参数校验和路径限制。
- 所有功能改动必须补充相应测试；提交前至少运行 `python -m unittest discover -s tests -p "test_*.py"`。
- 并行写代码使用独立 Git worktree/分支；多个任务直接共享当前目录时，只允许只读检查或串行修改。
- 不在根目录留下临时下载、截图或探测文件；这些内容进入被忽略的 `tmp/`。

## 代码边界

- `paper_data_agent/ui/` 只能组织界面与用户交互，不实现检索、排序或论文解析算法。
- `paper_data_agent/discovery.py` 负责发现与推荐，不直接操作 Tk 控件。
- `paper_data_agent/library.py`、`core.py`、`embeddings.py`、`reading.py` 负责论文数据与检索，不依赖 GUI。
- `paper_data_agent/workflow.py` 负责 Agent 编排，只通过稳定工具接口使用论文库和输出能力。
- PPT 与科研图功能不得反向依赖首页推荐或 GUI 主窗口。
- 外部 API、网页下载和本机 PowerPoint 属于基础设施边界，必须允许模拟测试和失败回退。

## 完成标准

“完成”必须同时满足：行为实现、错误路径明确、自动测试通过、文档与真实能力一致、没有提交用户数据或密钥。仅生成文件或仅看到工具调用成功不算完成。
