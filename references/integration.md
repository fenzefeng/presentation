# 跨项目接入 presentation

## 能力包与宿主边界

整个 `skills/presentation/` 现在就是可复制的 skill 能力包：

```text
presentation/
  SKILL.md
  requirements.txt
  config.template.json
  scripts/
    run.py
    presentation_core/
      service.py / planner.py / model_worker.py
      render_research.py / render_html.py / render_pptx.py
      agent.py / runtime.py / contracts.py
      contracts/ / prompts/ / visuals/ / examples/
  references/integration.md
  tests/
```

生成核心、材料快照、来源合并和生成执行器不导入 Fusion，也不要求 MySQL、Redis、QwenPaw 或 AgentScope。复制这个完整目录即可携带实现；仍需在目标 Python 环境安装 requirements、配置模型与凭据。模型通过 skill 决策，实际生成由这些脚本执行，并不是只靠 SKILL.md 生成文件。

HTML 将研究页样式和交互内嵌到单文件，PPTX 使用可编辑原生图表。生成两种格式都不要求浏览器依赖。旧版 HTML 仍可离线渲染。旧版本配置名兼容映射到新版，无须修改数据库结构或模型接口。

本项目的宿主适配保留在 Fusion：`fusion/runtime/presentation.py` 加载项目 skill 的同一份代码、注册 AgentScope 工具，装配私有任务上下文并处理执行/下载；`fusion/runtime/presentation_stage.py` 隔离可选演示子进程及截止时间；`fusion/chat/presentation_history.py` 读取授权会话并归档。无需将这些适配和 Fusion 的数据库、队列或登录系统复制到其他项目。

## 独立运行

以下命令中的 `/target/skills/presentation` 是复制后的目录，可以位于任意项目。将配置模板复制到目标项目私有目录并填写实际值。

```bash
python -m pip install -r /target/skills/presentation/requirements.txt

# 不调用模型，先验证生成环境；PPTX 改为 --deck .../deck.json
python /target/skills/presentation/scripts/run.py render \
  --input /target/skills/presentation/scripts/presentation_core/examples/research-request.json \
  --research /target/skills/presentation/scripts/presentation_core/examples/research.json \
  --output-root /absolute/private/output

# 调用目标项目配置的模型生成 HTML 或 PPTX
python /target/skills/presentation/scripts/run.py generate \
  --input /absolute/request.json --config /absolute/private/presentation.json
```

模型子进程根据当前包名启动，工作目录是 skill 自己的 scripts，不依赖原仓库工作目录、PYTHONPATH 或 fusion.presentation 包。已通过“将整个 skill 复制到临时目录，在仓库外运行”测试，包括 HTML/PPTX 渲染和模拟模型 HTTP 调用。

## Python 接入

在目标项目启动时加载 skill 自带模块，然后由工具包装调用：

```python
import sys
from pathlib import Path

skill_dir = Path('/target/skills/presentation')
sys.path.insert(0, str(skill_dir / 'scripts'))
from presentation_core import generate

result = generate({
    'schema_version': '1.0',
    'analysis': analysis_text,
    'sources': sources,
    'target_format': 'html',
    'series': series,
}, config=presentation_config)
```

配置中的 deployment_config 包含 arms（模型 URL、模型名、凭据文件名）；credential_dir 和 output_root 使用目标机器的私有目录。也可传入具有 `plan(request, *, deadline, cancel)` 方法的 planner，使用目标项目自己的模型客户端。不要复制实际密钥、数据库或本机部署配置。

请求、结果、研究内容及 PPTX Deck 的 schema 位于 `scripts/presentation_core/contracts/`。可选的 `series` 由宿主提供，每项有 `source_id`、`unit`、`points`（日期与数值列表）及可选的 `frequency`。HTML 直接使用观测值和对应指标名称。模型提交结论标题 `headline`、摘要 `conclusion`、优先指标 `focus_ids` 和按价格、库存、供应、需求组织的解读 `insights`。离线渲染兼容缺少 `headline` 的旧计划。PPTX 的 `requested_slides` 支持 1 至 12，成品页数等于 `slides` 的项数，报告标题和副标题随第一页正文展示。旧式分页 HTML 文件仍采用自身的页数约束。研究页的结果沿用 `slide_count` 字段，值为 0。

## 预览和 PDF 交付边界

| 层 | 职责 |
| --- | --- |
| Skill | 生成连续研究页、离线筛选与明细，并维护样式和打印排版。页面用容器查询适配 iframe 实际宽度。 |
| 宿主后端 | 从已完成分析中保留有界的原始观测，按现有会话权限提供附件。Fusion 最多保留 12 项、1200 个观测，每个读数窗口取最近 200 个原始点。预览仅放行对应已安装资源的脚本哈希。 |
| 宿主前端 | 承载隔离 iframe，管理侧栏拖动、放大、还原，以及 HTML 和 PDF 下载。 |
| DataRetrieval PDF 导出 | 按附件 ID 校验访问权限，用隔离浏览器读取归档 HTML。导出时展开数据明细，长表格按行分页并重复表头。PDF 使用归档研究页的默认视图。 |

外部 DATA 路由偶尔仅在已完成答复中返回带单位的 Markdown 日期表。Fusion 在其指标编码、单位、日期范围和日期读数能与外部服务的验证结果匹配时，保留表格中的点供演示复用。

PDF 导出由 DataRetrieval 宿主提供，可对已有 HTML 附件重新导出，无需再次调用展示模型。其他宿主可根据需要接入同类功能。

## Agent 工具契约

目标 Agent 加载 SKILL.md，并注册以下工具；工具名与参数保持一致即可使用相同指引。

### presentation_history(message_ids)

message_ids 是最多 20 个字符串的数组。空数组列出索引：

```json
{"materials":[{"message_id":"m1","preview":"分析摘要","sources":1}],"history_truncated":false,"history_error":null}
```

指定 ID 返回完整材料：

```json
{"materials":[{"message_id":"m1","analysis":"完整正文","sources":[{"id":"D1","title":"来源","description":"口径与期间"}]}]}
```

目标宿主只提供当前用户、当前会话、当前问题之前的完整材料，标记历史截取和读取失败。不能把所有用户的消息交给模型后让它自行判断权限。

### create_presentation(analysis_message_ids, target_format)

当前或历史分析均由执行器按 ID 读取已完成的正文及来源。Fusion 先完成原有分析流程，再将结果作为只读材料提供给演示阶段；不向展示模型开放编写行业分析的参数。target_format 为 html 或 pptx。成功返回 status=succeeded 和 artifacts，失败返回 status=failed 和 error；不把磁盘路径或模型凭据作为模型参数。

可直接使用 `presentation_core.runtime.PresentationSkill`，向构造函数提供 context（config_file、run_id、materials、phase="presentation"、target_format）、session 和 evidence 回调，再将它的 history/generate 方法包装成上述两个工具。session 适配器需提供 id、reference_date、limits，以及 event、counts、call(stage, fn)；宿主用这些接口落实任务预算和取消。也可自行实现上述契约，调用通用 generate，而不使用这层会话执行器。

宿主负责将 artifacts 归档，生成可用下载地址并在前端展示。当前 Fusion 附件允许完整链接匿名下载，聊天历史仍需登录；其他项目可按自身产品约定实现下载权限。
