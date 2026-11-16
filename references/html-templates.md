# 更换 HTML 参考模板

HTML 模板在展示阶段生效，不修改 Fusion 的问题路由、分析提示词、垂直模型调用或分析正文。PPTX 是独立的可编辑原生渲染，切换 HTML 模板不会自动改变 PPTX。

## 已接入模板之间切换

只改 `scripts/presentation_core/visuals/html-templates.json` 的 `default`：

```json
"default": "knowledge-arch-blueprint"
```

当前默认使用该蓝图模板。恢复之前的中文产业研报主题时改为 `commodity-v2`。不要修改私有配置中的 template_version 来切 HTML 模板；那个字段沿用 PPTX 渲染版本契约。

注册表保存模板的 body_class、styles、prompt 和 version；upstream 来源路径相对于本 skill 根目录。生成时，model_worker 读取对应的组件指引，render_html 将对应 CSS 与离线交互内嵌到单文件。最终文件记录 presentation-template 元信息，重复规范化保留该文件已选模板，不会因为之后切换默认值而自动换肤；以前已经下载/归档的文件不改写。没有模板元信息的旧式受管 HTML 在重新渲染时使用当时的默认模板。

## 这次实际使用的蓝图资源

- 完整参考：[knowledge-arch-blueprint/index.html](../third_party/html-ppt-skill/templates/full-decks/knowledge-arch-blueprint/index.html)。
- 原样复制并实际内嵌的 CSS：`scripts/presentation_core/visuals/templates/knowledge-arch-blueprint/style.css`，与参考目录的 style.css 一致，MIT LICENSE 随资源保存。
- 适配 CSS：同目录 `adapter.css`。将参考样式接到1280×720公共组件，处理中文字号、图表、来源分栏、手机和打印，并保留网格、锈红重点块、黑色描边卡片和流程节点。
- 内容布局指引：`scripts/presentation_core/prompts/html-blueprint.md`。要求模型使用 kb-cover-top、kb-insight、kb-card、kb-pipeline 等组件，以实际分析填充内容；不复制参考演示中的知识库、代码和产品宣传。
- 公共骨架和交互仍为 commodity.css / commodity.js。commodity-v2 的文档标识是结构契约，不再用来区分具体视觉模板；实际模板以 presentation-template 元信息和 data-template 区分。

## 加入另一个模板，例如 course-module

1. 阅读本 skill 内 `third_party/html-ppt-skill/templates/full-decks/course-module/index.html` 和 style.css（仓库路径为 `skills/presentation/third_party/html-ppt-skill/…`），确定要复用的封面、内容页、对比/流程等组件。
2. 在 `visuals/templates/course-module/` 放入原样样式与许可证，编写 adapter.css，将相应组件接入公共 slide、chart-panel、sources、notes 结构及离线运行时。若字体或图片需要外部网络，改成随 skill 打包或系统字体回退。
3. 增加 `prompts/html-course-module.md`，描述内容如何放入该模板的组件，不复制示例主题、数字或固定页数。
4. 在 html-templates.json 的 templates 中新增条目，然后将 default 改为它。仅提供样式/提示词的模板不需要再修改 Python 选择代码。
5. 验证真实生成与旧模板、页数约束、桌面/手机/打印排版、图表数据及仓库外复制运行。新增模型使用的组件类若有特殊交互，才需要扩展 commodity.js；若改变正文数据结构，才需要调整契约和渲染器。

当前 course-module 仍是参考资源，未适配注册，不能只写进 default 就使用。
