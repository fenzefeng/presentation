# 中文产业研究视觉规范

适用于维护展示提示词、增加组件或检查生成文件。研究内容由 Fusion 产出；展示模型只做重组与表达。

## 从内容选择视觉

| 材料 | 展示方式 | 需要保留 |
|---|---|---|
| 一组关键观测值 | 2–4张指标卡 | 日期、单位、统计口径；变化注明环比/同比 |
| 同口径连续数据 | 折线图 | 真实时点和数值，非零纵轴有标识 |
| 同单位横向比较 | 柱图 | 零基线、分类和单位 |
| 定性的产业链关系 | 3–4步传导链 | 原分析中的因果与条件，不伪装成已发生事实 |
| 供应/需求、支撑/压力 | 双栏对比 | 共同口径、分歧与限制 |
| 不同条件下的判断 | 2–4格情景卡 | 触发变量、已有影响，不新增概率/目标价 |
| 精确数据与统计口径 | 简洁表格 | 含表头至多5行，至多5列，数值单位清楚 |
| 摘要和跟踪事项 | 结论卡/短要点 | 一页一个结论，长解释进入讲解备注 |

缺少连续观测就不画趋势。不同单位不共用数轴，不自动生成指数，不对缺测插值。原生图表保存输入数值，允许后续在 PowerPoint 编辑数据。上涨红、下跌绿仅编码方向，不表示利好或利空。

## 设计系统与实现

统一16:9画布。HTML 当前使用 knowledge-arch-blueprint 的奶油纸、墨黑描边、锈红强调与蓝图网格；PPTX 保留纸色 `#f5f3ed`、墨色 `#19343d`、青绿 `#087f82`、铜色 `#b17448`。采用中文无衬线字体：Noto Sans CJK SC / 微软雅黑 / 苹方。PPTX 声明东亚字体；交付机器未安装首选字体时由办公软件替代。

HTML 由模型生成语义组件，`commodity-v2` 文档结构标识触发离线主题和交互注入，具体模板由 html-templates.json 选择；重复规范化不重复插入，也保留文件已选模板。`scripts/presentation_core/visuals/commodity.css` 与 `commodity.js` 会内嵌到最终单文件，无 CDN、外部图片字体或运行时依赖。手机使用可读的纵向组件，桌面固定画布等比缩放；支持方向键、目录、讲解备注、全屏、触摸翻页和逐页打印。图表使用内嵌 SVG，悬停点可读数值。

PPTX 独立使用 `render_pptx.py` 渲染可编辑原生形状、表格、图表与备注；本次 HTML 模板切换不改变 PPTX 配色。旧版 bullets/two_column/table Deck 仍可渲染，旧版无主题标识 HTML 保持兼容；旧配置版本名自动兼容，无须改作者的数据库或部署路径。

## 检查方式

- 在 ffz 执行 `python -m unittest discover -s skills/presentation/tests -v`，覆盖渲染、数据维度、非有限数值、资产内嵌与可迁移性。
- 用 examples/commodity-request.json、commodity-deck.json 和 commodity.html 生成两种文件。示例明确是合成数据，不是真实行情。
- 在浏览器逐页查看标题、文字、图表坐标、页脚和备注，检查桌面与手机无裁切、横向溢出；打印后每页16:9，图表正常。
- PPTX 检查图表数据工作簿、文字/表格可编辑、形状在画布内，并用 PowerPoint/LibreOffice 检查最终字体与分页。结构检查及按形状绘制的预览不能替代 Office 实际渲染。

## 参考来源

完整参考项目已放入本 skill 的 [third_party/html-ppt-skill](../third_party/html-ppt-skill/)，上游为 [lewislulu/html-ppt-skill](https://github.com/lewislulu/html-ppt-skill)，固定版本 `fd1629067909ff55b36b905476de4e5f26062a1f`。快照保留原始文件和 [MIT 许可证](../third_party/html-ppt-skill/LICENSE)，来源与快照校验信息见 [upstream.json](../third_party/html-ppt-skill.upstream.json)。不需要本机项目外的 `~/html-ppt-skill`。

参考入口：[整套演示模板](../third_party/html-ppt-skill/templates/full-decks/)、[单页模板](../third_party/html-ppt-skill/templates/single-page/)、[主题](../third_party/html-ppt-skill/assets/themes/)、[原始使用说明](../third_party/html-ppt-skill/SKILL.md)。这些资源随 presentation skill 一起提交和交付；它们是参考资源，不作为另一个 Fusion skill 注册。

当前生成器借鉴了其设计令牌、固定画布、内容组件、目录/备注与截图复核思路，针对中文大宗商品研究重新编写，并增加独立的原生 PPTX 输出。复制参考快照不会自动切换生成器或启用整套模板库。现在已单独适配并注册 knowledge-arch-blueprint，其原始 CSS 实际内嵌到输出中；其他模板仍仅供参考。切换方法见 [模板切换说明](html-templates.md)。生成代码、离线视觉资源和完整参考库均位于 presentation skill 中，迁移时复制整个 `skills/presentation/` 即可。
