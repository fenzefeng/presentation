# presentation

版本号见 [SKILL.md](SKILL.md) 的 `metadata.version`；每轮迭代完成时同步递增。

面向中文大宗商品研究的 HTML 与可编辑 PPTX 演示技能。输入已完成的分析正文及来源，输出演示文件；行业分析由宿主 Fusion 模型完成。本技能不重新查询行情，不负责垂直模型分析。

HTML 默认生成响应式研究长页，按实际预览宽度重排，离线可用。页面由首屏结论、关键指标、指标趋势、关键解读和数据明细组成。有真实时序时默认展示交互式折线图，可筛选指标和日期范围、悬停或点按查看观测值。PPTX 默认一页，支持指定 1 至 12 页，首页合并报告标题和正文，文本、形状、表格及图表可编辑。

接入 DataRetrieval 后，可从演示预览下载 PDF。DataRetrieval 从归档的 HTML 导出 PDF，展开数据明细并为长表格分页。独立 CLI 提供 HTML 和 PPTX 两种输出。

## 安装到 QwenPaw

发布后，将本仓库 URL 用于原生安装：

```bash
qwenpaw skills install <本仓库URL> --agent-id fusion
qwenpaw skills list --agent-id fusion
```

`fusion` 是示例工作区 ID，需在 QwenPaw 配置中存在，可换成实际目标 Agent ID。未指定 `--agent-id` 时安装进入共享技能池，不直接提供给某个 Agent。

**安装 skill 文件不等于完成宿主接入。** 当前指引使用 `presentation_history`、`create_presentation` 两个专用工具，宿主需要提供它们、模型配置和文件交付接口。DataRetrieval 的工作区接入代码位于该项目，未包含在本独立仓库中。具体契约见 [接入说明](references/integration.md)。

依赖安装到已有 Python 环境，不需要新建环境：

```bash
python -m pip install -r requirements.txt
```

将 `config.template.json` 复制到仓库外的私有目录，填写部署配置、模型凭据目录和输出目录；模板中的 `${...}` 必须替换为实际绝对路径，不会自动展开。不要提交实际配置或凭据。

## 独立使用

不需要 Fusion、MySQL、Redis、QwenPaw 或 AgentScope，也可直接运行脚本。

离线渲染示例，不调用模型：

```bash
python scripts/run.py render \
  --input scripts/presentation_core/examples/research-request.json \
  --research scripts/presentation_core/examples/research.json \
  --output-root /absolute/private/presentations

python scripts/run.py render \
  --input scripts/presentation_core/examples/commodity-request.json \
  --deck scripts/presentation_core/examples/commodity-deck.json \
  --output-root /absolute/private/presentations
```

调用配置中的展示模型：

```bash
python scripts/run.py generate --input /absolute/request.json \
  --config /absolute/private/presentation.json --format html
```

输出 JSON 中的 artifacts 给出文件信息。示例数据均为合成数据。内容与来源需人工复核，生成成功不表示行业结论已经核实。

## 维护与验证

- [接入与迁移](references/integration.md)说明研究数据契约、预览分工和 PDF 导出边界。
- [旧版模板](references/html-templates.md)和[幻灯片视觉规范](references/visual-design.md)用于维护既有幻灯片。

```bash
python -B -m unittest discover -s tests -q
```

自动检查包括结构、图表数据维度、页数与部分布局边界；每次生成不会自动执行浏览器截图或 Office 渲染复核。PPTX 最终效果需在 PowerPoint/WPS 中检查。

QwenPaw 安装结果是工作区文件副本，不能默认对其执行 git pull。更新时需保存技能配置，再按目标版本重新安装或使用宿主提供的同步流程；常驻宿主进程加载了 Python 模块时需要重启。

包内包含模型 HTTP 调用与子进程代码。QwenPaw 的静态扫描可能产生告警；不同扫描策略下是否允许安装，需要目标环境自行审查。本技能不要求关闭扫描或加入白名单。

## 许可与来源

沿用原 DataRetrieval 项目的 [MIT 许可证](LICENSE)，保留原版权声明。第三方快照来自 `lewislulu/html-ppt-skill`，其 MIT 许可证、固定版本及校验记录保留在 [third_party/](third_party/)。
