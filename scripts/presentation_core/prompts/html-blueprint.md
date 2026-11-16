【本次 HTML 模板：knowledge-arch-blueprint】
实际使用参考项目的奶油纸建筑蓝图模板：细网格背景、黑色描边白卡片、锈红重点块、编号流程节点、简洁图纸页脚。以下模板组件指引覆盖通用提示中封面的默认排列。主题样式由程序内嵌，不生成 CSS 或 JS，不复制参考演示中的知识库/AI/产品介绍内容。

- 继续使用公共文档标识 presentation-theme=commodity-v2、body data-theme=commodity、main.deck 和 section.slide。程序添加具体模板标识、模板 class、网格和页脚。
- 封面使用 section.slide.cover，内部为 div.kb-cover-top。左侧 div 内放 p.eyebrow.kb-kicker、h1.kb-h1、p.lede.kb-sub；右侧为 aside.kb-insight，先 span.kk“核心判断”，再放材料已有的一句研究结论（35字以内）。h1 不超过24汉字、最多两行，可用 span.rust 强调品种或关键词。副标题不超过45字。封面底部 p.cover-meta 保留时期和材料性质。
- 如材料本身含明确的3–4步传导机制且页数允许，可在封面主标题区下放流程条；不要为了装饰复制正文、占满封面或增加虚构步骤。
- 正文保留 header.slide-header 与 div.slide-content。标签用 p.eyebrow.kb-kicker，标题用 h2.kb-h1。结论标题与原分析一致，不再做行业分析。
- 摘要/对照/情景卡使用 article.card.kb-card；需要强调时为一张卡增加 accent。两栏使用 div.grid.g2.kb-grid-2；三栏用 div.grid.g3。每卡 h3 和短段落，不把整段分析塞入卡片。
- 传导链使用 div.process.kb-pipeline，内含3–4个 article.step.kb-step。各节点依次 span.step-no.kb-step-num、h3.kb-step-title、p.kb-step-body。只有原分析明确存在核心环节时，才给对应节点加 hero。每节点说明40字以内，区分条件传导与已发生事件。
- 指标卡、图表 JSON、表格、来源和备注继续使用通用组件。图表颜色随当前模板切换为锈红/墨黑；不混用单位，不补造数据。来源多时保留简洁的“ID、指标名、单位、时期”，程序使用紧凑分栏，避免大段解释导致来源页溢出。
- 不机械沿用参考项目的8页结构。封面、内容和来源按本次真实材料及页数要求组织；不增加代码页、产品宣传页、谢谢页，也不将原参考模板示例的数字当作分析事实。
