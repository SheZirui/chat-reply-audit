# 完整操作：从一份聊天文件到逐条复核报告

[返回首页](../README.md) · 尚无可读文件？先读[数据来源与输入准备](DATA_PREPARATION.md)。本流程从已合法取得、获准处理的 CSV/JSON 开始。

> [!WARNING]
> 本项目不提供数据提取或解密操作，来源风险见[数据获取风险说明](HIGH_RISK_EXPORT.md)。本机分析的同意不自动包含把正文交给在线 Agent 或 API；不接受外发时选择人工或本地模型。

目录：[虚构演练](#0-先用虚构数据走通) · [输入与阶段](#1-准备真实输入与阶段) · [统计](#2-本机统计先不让模型看正文) · [上下文](#3-提取候选上下文) · [人工](#4a-人工本机离线复核) · [Codex](#4b-交给在线-codex-复核) · [API](#4c-在线-api-复核) · [本地模型](#4d-本地模型复核) · [生成报告](#5-生成报告并核对)

## 0. 先用虚构数据走通

在解压得到的 **chat-reply-audit 根目录**打开 PowerShell，执行下面命令。不配置 API，不读取聊天软件，不发送真实内容：

```powershell
python scripts/reply_audit.py analyze --input examples/demo.csv --phases examples/phases.json --as-of 2030-01-07T18:00:00+08:00 --out private-output/tutorial-stats
python scripts/reply_audit.py prepare-review --input examples/demo.csv --analysis private-output/tutorial-stats/analysis.json --include-content --out private-output/tutorial-context
python scripts/reply_audit.py review-workbench --packet private-output/tutorial-context/context_packet.json --out private-output/tutorial-desk
```

看到的预期结果：34 条有效消息，11 个超过 4 小时的候选；提取 11 个上下文。用本机浏览器打开 `private-output/tutorial-desk/index.html` 即可试填；页面含的是虚构消息。

如果只想先看完整结果，用预先编写的虚构审阅答案：

```powershell
python scripts/reply_audit.py apply-review --packet private-output/tutorial-context/context_packet.json --reviews examples/demo-reviews.json --out private-output/tutorial-result
```

打开 `private-output/tutorial-result/report.html`。预期：2 项保留、2 项重新确定话题起点、6 项收尾、1 项不确定。样例答案是人预写的测试材料，不是实际调用大模型得到的成绩。不能把这份 answers 文件用于自己的聊天。

所有输出目录需为空或不存在。重跑时换目录后缀，例如 `tutorial-stats-02`，后续命令同步更换路径；不要覆盖之前的结果。

## 1. 准备真实输入与阶段

把一个双人会话的兼容 CSV 保存为项目旁边的 `private-chat-data/input/chat.csv`。目录创建、支持来源与格式核对见[数据准备](DATA_PREPARATION.md)。基础统计可以没有正文；语义复核则需要同一份文件里有正文。统计后更改文件会触发指纹不匹配，需要重做统计与上下文。

方向先在本机核对：中文 CSV 的“是否我发送＝是”映射 A，本人；“否”映射 B，另一方。标准 CSV 默认把输入中首次出现的有效发送者作为 A，不一定是自己；用 `--sender-a '输入中本人的精确发送者值'`明确指定。该参数可能进入本机历史，避免在共享终端录制中操作。统计和准备上下文要用相同映射。

需要按关系阶段、工作日程或其他节点分开时，在本机编辑 `private-chat-data/input/phases.json`。下面所有日期、阶段均为虚构，请换成自己要研究的日期：

```json
[
  {"name":"阶段一","start":"2030-01-01","end":"2030-01-05"},
  {"name":"阶段二","start":"2030-01-05","end":"2030-01-08"}
]
```

`start`包括、`end`不包括。例如想包含 1 月 7 日全天，`end`写 1 月 8 日。阶段不能重叠，空隙不属于任何阶段。相邻阶段的跨界等待单列，不分摊、不重复计数；事件未被纳入阶段主表也不等于不存在。阶段名会出现在报告里，不建议用真实姓名。

## 2. 本机统计，先不让模型看正文

```powershell
python scripts/reply_audit.py analyze --input ../private-chat-data/input/chat.csv --timezone +08:00 --phases ../private-chat-data/input/phases.json --candidate-minutes 240 --thresholds 120 180 240 --out ../private-chat-data/output/stats-01
```

不分阶段时删去整个 `--phases ...` 参数。标准 CSV 需要指定本人时加 `--sender-a ...`。固定时区按实际数据设置；默认 +08:00，不自动处理夏令时地区的历史规则。默认统计截止于文件末条有效消息，若想观察至某个已知截止时刻可加 `--as-of 2030-01-08T18:00:00+08:00`，不要拿示例截止时间用于自己的记录。

**成功标志：** 终端只显示有效条数与候选数，输出目录有 `report.html` 和 `analysis.json`。打开报告核对日期范围、A/B 方向、每阶段样本数量、系统消息排除与重复消息计数。显示格式错误或多会话错误时先修输入，不要删行凑结果。

**统计含义：** 同一发送者连续发言形成一个时间段，另一方首次发言结束间隔。第一条／最后一条是两种口径；恰好 4 小时不计入“超过 4 小时”。2、3、4 小时的次数是嵌套关系，不可相加。平均数包含过夜和长停聊；结合中位数、90 分位及样本量看，不能直接当作真实期待等待。

程序会在本机读取文件以解析、去重，不会在基础报告输出正文；不等于文件已匿名。若让在线 Agent 打开原文件或打印记录，仍可能把正文交给模型。只要你仅需要统计，到这里就可以停止。

## 3. 提取候选上下文

“上下文复核”指回到候选前后的实际消息，判断是否还留着待回应事项，以及真正起点。不是再次比较两个时间戳，也不能只搜“晚安”就判结束。

```powershell
python scripts/reply_audit.py prepare-review --input ../private-chat-data/input/chat.csv --analysis ../private-chat-data/output/stats-01/analysis.json --include-content --out ../private-chat-data/output/context-01
```

如上一步用了 `--sender-a`，此步也要相同。输出：

- `context_packet.json`：候选事件与正文。每项 `before` 是前文，`waiting` 是对方首次发言前的连续消息，`after` 的第一条是下一方首次发言，后面继续保留后文。
- `reviews_template.json`：相同候选编号、尚未审阅的空白表。它不包含一份自动完成的结论。

默认前 8 条、整个 waiting 段、后 10 条，每条最多 1200 字符。**默认窗口可能缺少关键解释**，整个 waiting 段也可能很长。截断会明确标记，不能把被截断的正文当作已经完整阅读。

可以只提取本次 `candidates.csv` 中你在本机选定的几个编号：

```powershell
python scripts/reply_audit.py prepare-review --input examples/demo.csv --analysis private-output/tutorial-stats/analysis.json --events E000007 E000030 --include-content --out private-output/tutorial-selected
```

上面是可直接运行的虚构演练。真实使用时替换为真实输入、统计路径及其候选编号；程序拒绝不在本次候选中的编号。缩小选取范围不改变全部统计，复核结果只代表所选子集。

需要更完整的前后文时，用同一输入和统计文件重新准备一个新目录：

```powershell
python scripts/reply_audit.py prepare-review --input ../private-chat-data/input/chat.csv --analysis ../private-chat-data/output/stats-01/analysis.json --include-content --before 30 --after 40 --max-message-chars 4000 --out ../private-chat-data/output/context-expanded
```

增加上下文会增加本机明文量、在线发送量和费用。使用扩展后的包重新审阅受影响项目，不要把旧理由当作已经看过新材料；同一分析的 ID 不变并不证明审阅者看过扩展内容。

## 4A. 人工、本机离线复核

不想发送正文给任何模型时，选这条。无需 API，无需在线 Agent 打开真实文件。

```powershell
python scripts/reply_audit.py review-workbench --packet ../private-chat-data/output/context-01/context_packet.json --out ../private-chat-data/output/desk-01
```

用本机浏览器打开 `desk-01/index.html`。这是一个内嵌正文的离线页面，不调用外部资源、模型或本机服务器；保存在你信任的浏览器中即可。浏览器扩展、云盘与本机软件仍有各自权限。页面不会自动保存，刷新或关闭前先下载结果。

每项依次做：

1. 读前文，确认前一个问答是否结束；读完整 waiting 段，看有无新问题或新分享；再读 after，是否在回答同一事项，是否解释晚回。
2. 选择下表分类。保留或重新起算时，在下拉框选 waiting 中真实消息 ref 作为起点；其他分类起点选“不设置”。
3. 勾选真正支持判断的消息作为证据；不要勾“看起来相关”但与理由矛盾的消息。
4. 填写“判断理由”和“背景说明”，区分可见事实与推测；明确解释、可能线索、未见解释分别选择解释状态。
5. 点“下载 reviews.json”，将下载文件移到 `private-chat-data/output/`，命名为 `human-reviews.json`。浏览器可能下载到系统“下载”目录，同样要私密保管。下载文件不自动写回工作台所在目录。
6. 按第 5 节运行 apply-review。界面允许暂存不完整记录，最终程序会检查证据、起点、阈值与完整性。

| 界面判断 / status | 判断依据 | 起点 |
|---|---|---|
| 保留 / retained | 可辨认的待答事项，起点校准后仍严格超过筛选阈值 | waiting 中真实 ref |
| 新话题 / restart | 旧事项收尾后另起新事项，校准后未超过阈值 | waiting 中新事项首条 ref |
| 已收尾 / closed | 旧事项已完成，未确认仍留待回应内容 | 不设置 |
| 约定延后 / agreed_deferral | 原文明示不急、稍后／次日再聊等 | 不设置 |
| 不确定 / uncertain | 关键媒体未识别、缺上下文或期待不清 | 不设置 |
| 未审阅 / unreviewed | 还没做判断 | 不设置 |

真实等待与“合理不合理”分开。例如确实 5 小时后答复问题，但原文说明当时在培训，仍可标 retained，同时记录解释。没有解释不等于没有理由，更不能证明故意冷落。

也可以直接复制模板，用本机编辑器填写 JSON。根对象的 `analysis_id`、`review_source` 和 `reviews` 数组必须保留；字段详解、虚构案例见[审阅指南](../references/review-guide.md)。不要复制样例编号覆盖真实编号。

## 4B. 交给在线 Codex 复核

这条路线意味着所选片段进入在线模型上下文，不属于“纯本机”。不是安装 Skill 就自动允许读取全盘。先安装项目 Skill（首页有说明），只授权指定候选包；不要给它原始数据库、密钥、完整账号目录或联系人列表。

可使用下面的请求，自行将路径换成候选包与新结果文件的位置：

```text
使用 $chat-reply-audit，只审阅我指定的 context_packet.json 中的候选。我理解这些片段会进入当前在线模型上下文。不要打开原始聊天、数据库、密钥或目录中其他会话，不调用额外 API。逐条读取 before、完整 waiting 和 after，引用真实 ref，校准起点，区分是否等待与可见解释。关键证据不足就 uncertain，不推断已读或感情投入。将完整结果保存为指定的新 reviews.json，review_source 必须是 model_suggestion，然后运行 apply-review。上下文不足时先说明需要补充哪一项，由我在本机扩大范围。
```

请求中还需明确提供本机文件路径；路径不是固定示例路径。约束提示不能代替实际文件权限。要求正文完全不交给在线服务时不要选择这条。

生成的模型建议可以预填离线工作台，自己继续检查：

```powershell
python scripts/reply_audit.py review-workbench --packet ../private-chat-data/output/context-01/context_packet.json --reviews ../private-chat-data/output/model-reviews.json --out ../private-chat-data/output/desk-model
```

表单编辑不会自动把 model_suggestion 改成人工确认。如果希望形成独立人工结论，可从空白工作台逐项审阅；不要只改来源标签来冒充人工完成。

## 4C. 在线 API 复核

与 4B 二选一即可，不需要把相同片段再发给第二个在线模型。需要自行选择服务，核实其数据保留与费用。当前实现只接受兼容 Chat Completions 的完整端点；不是任意网站链接。

在自己本机的 PowerShell 配置，下面域名／模型名是配置占位符，必须替换为服务商文档中的值：

```powershell
$env:CHAT_REVIEW_API_URL = "https://api.example.com/v1/chat/completions"
$env:CHAT_REVIEW_MODEL = "provider-model-name"
```

想照一个具体服务配置时，可选 DeepSeek：先在它自己的[开放平台](https://platform.deepseek.com/)登录并创建 API Key、查看余额及数据政策，再在本机设置如下值。按 2026-10-24 核对的[官方首次调用文档](https://api-docs.deepseek.com/)，完整端点与示例模型为：

```powershell
$env:CHAT_REVIEW_API_URL = "https://api.deepseek.com/chat/completions"
$env:CHAT_REVIEW_MODEL = "deepseek-flash"
```

这里没有填写真实密钥。模型名、可用性和收费以你调用当天的官方说明为准；本项目没有用真实私聊或真实付费请求做该服务联调，参数兼容不等于语义准确率经过验证。不使用这个服务则跳过这组设置，不能把其他服务的密钥交给它。

不要把真实密钥写入教程、脚本、聊天或命令参数。可以在本机用隐藏输入临时设置环境变量：

```powershell
$reviewSecret = Read-Host '在本机输入 API 密钥，不要发送给聊天助手' -AsSecureString
$reviewPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($reviewSecret)
try {
    $env:CHAT_REVIEW_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($reviewPointer)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($reviewPointer)
    Remove-Variable reviewSecret,reviewPointer
}
```

环境变量仍会以进程可用形式存在，不是防本机恶意程序的密钥保险箱。程序不会读取 `.env`，也不需要把环境变量值粘贴进 Agent 对话。

先试选定包中的前 2 项，只预览数量，不联网、不显示正文：

```powershell
python scripts/reply_audit.py review-api --packet ../private-chat-data/output/context-01/context_packet.json --max-cases 2 --dry-run
```

`--dry-run`不是正文预览，也不证明 API 已配置正确；先在离线工作台查看即将发送的对应前 2 项。如果只想发送某几个指定事件，先用 `prepare-review --events`生成只含它们的包。

确认范围和服务后实际发送：

```powershell
python scripts/reply_audit.py review-api --packet ../private-chat-data/output/context-01/context_packet.json --max-cases 2 --send-content --attempts 1 --timeout 60 --out ../private-chat-data/output/model-reviews-trial.json
```

默认每项一次请求；试跑未选中的项保留“未审阅”。模型错误、无效引用、超长片段或请求失败会保留不确定，不伪造结论。`--max-case-chars`是字符上限，不是模型 token 上限或费用估算。默认 JSON 模式和 `max_tokens`可能被某些提供方拒绝，确认其文档后再使用 `--no-json-mode`等选项。

试跑后按第 5 节生成部分报告，自己核对推理。决定审阅全部时，删去 `--max-cases 2`，选择一个新输出文件名；**会重新请求试跑项目，不会自动跳过，可能重复收费**。不要反复加重试或悄悄改服务。移除当前会话密钥：

```powershell
Remove-Item Env:CHAT_REVIEW_API_KEY -ErrorAction SilentlyContinue
```

## 4D. 本地模型复核

需要已经安装、下载并启动一个提供兼容接口的本机模型服务。本项目不安装模型。以你选用服务的官方文档为准：加载模型，在开发者／服务器界面启用兼容 Chat Completions 的接口，限制为回环地址，确认实际端口和模型标识。模型下载通常需要联网，推理是否另有遥测、日志或远程回退由该软件决定。没有验证本机部署时，可先选 4A 人工路线。

例如使用 LM Studio，可按以下步骤准备（按 2026-10-24 官方文档核对界面与接口，未在本项目联调）：

1. 从 [LM Studio 官网](https://lmstudio.ai/)安装适合自己系统的版本。在其模型搜索／下载界面选一款本机内存能加载、支持中文指令的模型，阅读许可并完成下载。本项目不指定一个保证适合所有硬件的模型。
2. 在 Chat 或 Developer 界面加载下载好的模型，先用虚构文字验证中文和 JSON 输出，不放真实聊天。
3. 打开 **Developer**，按[官方本地服务说明](https://lmstudio.ai/docs/developer/core/server)开启 **Start server**。仅监听 localhost／回环地址，不开启局域网共享，也不启用远程回退。
4. 从服务界面取得模型 identifier 和端口。下文假设端口 1234，完整地址使用 `/v1/chat/completions`，不是只有 `/v1`。接口说明见[官方兼容文档](https://lmstudio.ai/docs/developer/openai-compat)。
5. 先对虚构 demo-context.json 试跑、核对 JSON 与引用，再决定是否在本机处理真实包。配置完成后可断网验证推理是否仍可用；这也不能证明软件未来永不联网。

下面只是常见接口形状；地址、端口、模型名应替换为你服务的实际配置，不保证某个应用默认相同：

```powershell
$env:CHAT_REVIEW_API_URL = "http://127.0.0.1:1234/v1/chat/completions"
$env:CHAT_REVIEW_MODEL = "your-loaded-local-model"
Remove-Item Env:CHAT_REVIEW_API_KEY -ErrorAction SilentlyContinue
python scripts/reply_audit.py review-api --packet ../private-chat-data/output/context-01/context_packet.json --max-cases 2 --dry-run
python scripts/reply_audit.py review-api --packet ../private-chat-data/output/context-01/context_packet.json --max-cases 2 --allow-local-endpoint --send-content --out ../private-chat-data/output/local-model-reviews.json
```

若本机服务需要密钥，用上节隐藏输入方式设置。`--send-content`在此表示把正文送到配置的服务，即使它在本机也要明确指定。`--allow-local-endpoint`只允许回环 HTTP，不允许远程明文地址；不要把远程云服务误称为本地。模型建议仍需人工核对，不因本机部署就保证正确。

## 5. 生成报告并核对

人工完成全部项目：

```powershell
python scripts/reply_audit.py apply-review --packet ../private-chat-data/output/context-01/context_packet.json --reviews ../private-chat-data/output/human-reviews.json --out ../private-chat-data/output/reviewed-01
```

API 试跑只做部分项目时：

```powershell
python scripts/reply_audit.py apply-review --packet ../private-chat-data/output/context-01/context_packet.json --reviews ../private-chat-data/output/model-reviews-trial.json --allow-partial --out ../private-chat-data/output/model-trial-report
```

打开输出的 `report.html`，逐条核对分类、引用的原文、起点和解释。JSON 是可继续处理的结果，CSV 便于对照；HTML 还包含完整所选上下文。所有这些都属于私密报告。模型建议的标题会明确写“尚未人工确认”。

若提示未审阅，不代表程序坏了：继续填写，或明确使用 `--allow-partial`保留未完成状态。若提示证据／起点／截断错误，按[排错与结果解释](RESULTS_AND_TROUBLESHOOTING.md)处理。apply-review 只能验证结构与引用是否存在，不能证明“这句话支持这个判断”。

复核不会改写原始统计或输入。完整等待、跨阶段等待、截止时尚未获回复的末尾事件彼此分开；当前上下文候选来自阶段主统计中的完整事件，跨界／末尾待定另看基础报告，不在本轮自动语义复核里。选取部分候选时，结论不能冒充全部聊天的发生率。

## 6. 最后保管和分享

保管输入、上下文、工作台 HTML、浏览器下载的 JSON、API 输出和报告。程序不自动上传或删除它们；同样不保证云同步、浏览器扩展或系统备份不接触文件。

对外展示优先使用仓库自带的虚构图和虚构报告。真实结果即使没有姓名，也可能通过时间、内容和经历识别当事人。发布代码时仅用白名单副本，见[发布审查](PUBLISHING.md)。
