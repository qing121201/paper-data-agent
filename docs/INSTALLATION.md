# 安装与验证

## Python 依赖

在项目根目录运行：

```powershell
python -m pip install -r requirements.txt
```

主要依赖：pypdf/PyMuPDF 读取 PDF，pandas 与 matplotlib 生成科研图，Playwright 渲染思维导图。Tkinter 随常见 Windows Python 安装提供，不由 pip 安装。

若 Playwright 没有可用浏览器，可运行：

```powershell
python -m playwright install chromium
```

程序也会尝试使用本机 Edge/Chrome。PPTX 自动生成和预览依赖 Windows 上已安装的 Microsoft PowerPoint；没有 PowerPoint 时，论文检索和问答仍可使用。

## 启动

双击根目录的 `启动论文Agent.cmd`。需要看到调试输出时，运行 `scripts/启动GUI调试版.cmd`。

## 自动测试

```powershell
python -m unittest discover -s tests -q
python -m compileall -q paper_data_agent
```

测试使用临时目录和模型替身，不需要真实 API Key。联网下载、PowerPoint COM 和不同模型服务商仍需要单独的人工验收，66 项测试并不等于所有外部服务永远可用。
