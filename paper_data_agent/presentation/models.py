"""Declarative layouts and model-facing schema for evidence-linked slide visuals."""

LAYOUTS = {"text", "image_left", "image_right", "image_top", "image_full", "two_images"}

VISUAL_SCHEMA = """页面可含 layout: text/image_left/image_right/image_top/image_full/two_images，
images: [{asset_id: 候选图片ID, crop: [x0,y0,x1,y1], caption: 中文图注}]。
crop 是相对于整张候选图片的 0–1 坐标，可省略表示使用整页。依据所看到的图像裁剪，
保留坐标轴、图例、标签，不捏造图或裁剪掉影响结论的条件。每页最多 2 张。
图文页正文最多 3 个短要点；图较复杂选 image_full 或 image_top。不把整页论文截图冒充单独提取的原图。
只引用提供的 asset_id，禁止编造图片路径。实际来源由程序写入图注。
也可以用 drawing 自绘图表（不能与 images 同时填写）：
流程图 {kind:"flow",title:"方法流程",nodes:["步骤1","步骤2"],source:"论文名与页码"}，2–6 个顺序步骤，nodes 必须是字符串数组，每项不超过 30 字，不使用对象；
优先 3–4 个简洁步骤；用户指定三步就返回 3 个节点，不要把每个子步骤展开。节点避免长句，每个节点推荐不超过 16 字。
数据图 {kind:"bar"或"line",title:"指标对比",labels:["方法A","方法B"],
values:[1.2,2.3],ylabel:"指标及单位",source:"论文名、页码与表格号"}。
数值必须逐项来自提供的原文证据或用户数据；条件不同不能强行比较；无可靠数据改画流程图。
自绘图应明确标注根据原文整理，不冒充原论文图。
"""
