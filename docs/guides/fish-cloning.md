# Fish Audio 持久音色克隆

核查日期：2026-10-08。此次接入为官方私有 fast 音色创建的最小流程，不覆盖全部 Fish API。

## 能力范围

| 能力 | 项目状态 |
| --- | --- |
| 查询本人公开音色、工作区/公共音色，手填 Voice ID | 支持，三种范围独立；选择器共用一个 Voice ID |
| 以 `reference_id` 合成、试听、工作台采用 | 原有功能；新克隆 ID 复用同一路径 |
| 上传保存的参考片段，创建持久远程 Voice ID | 本次新增，单片段、私有、fast |
| 查询 created/training/trained/failed 状态、本地持久记录 | 本次新增，手动查询；结果未知不自动重传 |
| 保存成音色生成规则 | 本次新增，默认 `s2.1-pro-free`，保存不触发合成 |
| 每次 TTS 请求附带 `references` 音频 | Fish 官方支持，但当前项目 Fish provider 未接线；不可与持久创建混称 |
| 多参考文件、远程编辑/删除/公开发布、PVC、Voice Design、实时流式、Fish ASR | 本次未接入 |

## 使用

已有 Fish 音色无需再次克隆。在“我的音色”新建 Fish hosted 音色，选择服务连接后可查询“我的公开音色（API 账号）”，也可切换工作区或所有作者的公共库。选择结果直接回填唯一的 Voice ID，保存后复用于试音和工作台；亦可直接粘贴已知 ID。查询/保存不触发合成。

本人公开库按官方 `GET /wallet/self/package` 返回的 `user_id` 调用 `GET /model?self=false&author_id=...`，并复核条目的 `author._id` 与 `visibility=public`。这里的本人是所选连接凭据所属的 API 账号，未必是浏览器已登录账号。只使用账号 ID，不展示或持久化账户套餐/余额。权限不足、代理不支持或身份/作者不符时明确报错，不退化成所有作者列表；可继续手填 ID。`self=true` 仅表示当前工作区所有权，不能冒称本人公开库。

1. 在外部服务连接的既有安全配置入口填写 Fish 凭据，使用官方 HTTPS 地址。支持 origin、`/v1` 或 `/v1/tts` 形式；本次克隆不支持自定义代理。
2. 在“声音库”导入、裁剪、保存参考片段，并填写及核对片段原文。当前应用限一段 25 MB 以内的 WAV；这是应用限制，不是声明 Fish 的接口上限。
3. 打开“Fish 远程克隆”，选择连接、素材和名称。上传对象、参考片段、原文和目标音色摘要常驻显示，无需展开。
4. 仅使用有权克隆的声音素材。创建会将片段和原文上传至 Fish Audio，费用/额度按 Fish 当前规则执行，Free 推理不保证创建免费。点击“上传片段并创建音色”完成本地校验并明确提交，不再要求额外勾选。
5. 提交后显示必要结果与远程 ID，处理中可更新状态；只有 `trained` 才允许保存为 Free 合成音色。官方说明 fast 可快速使用，但本实现保守等待明确就绪状态。
6. 保存后在“我的音色”手动试音，或前往工作台选用。不会自动生成试听，也不会在 Free 失败时切换付费模型。已有明确保存的模型选择不被改写。

## 失败与恢复

网络超时、异常响应或进程中断可能意味着远程已经创建。此时显示“结果未知”，同一提交编号不会再次上传。先在 Fish 工作区核查；若找回 ID，可在“我的音色”手动绑定。不要直接新建重复音色。远程失败和未知状态均不代表克隆成功。

点击提交时的本地校验绑定连接版本、素材版本、文件摘要、原文和名称；校验与上传之间发生变化会拒绝提交。原连接之后发生变化时，状态查询/保存会阻止沿用新连接访问旧记录，并提示手动核查。凭据只由现有后端连接解析，界面和持久克隆记录不保存密钥或上游错误正文。

“删除本地记录”经一次确认后直接删除本地回执，无法撤销。不向 Fish 发送删除请求，不修改云端音色、已保存音色或素材。远程 `created`/`training` 状态暂不允许删除；正在上传的请求先完成回执写入再处理删除。结果未知及中断回执可以删除，只保留最小提交编号和校验摘要防止重复上传。旧版隐藏记录会重新列出供显式删除，不自动迁移或清理。

请求显式关闭 `enhance_audio_quality` 与 `generate_sample`，并发送已确认 `texts`，避免省略原文带来的隐式转写。未推定创建接口免费；Free TTS 的定价不能推出创建音色的费用。

## 验证与真实测试前置条件

`tests/test_fish_cloning.py` 使用生成音频、假凭据和 HTTP MockTransport，覆盖 multipart 参数、校验失效、重复/并发提交、超时、错误脱敏、远程状态、保存与现有合成/工作台路径，以及本地直接删除、去重保留、运行中删除排序和既有音色/素材不受影响。

运行相关 Python 套件：fish_cloning、speech_voice_catalog、speech_providers、speech_rules、speech_store、speech_http。前端聚焦测试为 `desktop/tests/fishClonePanel.test.mjs`，覆盖常驻摘要、无勾选的单次提交、重复点击、失败/未知响应、直接删除及运行状态保护。`desktop/tests/fixtures/fish-clone.html` 是全模拟浏览器夹具，不连接后端/Fish。

真实测试尚未进行。需用户选定有权使用的素材、确认上传目的和本次费用/额度，且在安全配置入口自行填写有效凭据。真实音色质量、账户 Free 权限及服务端实际状态转换仍需授权后验证。

## 官方依据

- [List Models](https://docs.fish.audio/api-reference/endpoint/model/list-models)：`self` 筛选工作区；`author_id` 筛选公开模型作者，仅在 `self=false` 时生效。
- [Get User Package](https://docs.fish.audio/api-reference/endpoint/wallet/get-user-package)：路径 `user_id=self` 与响应 `user_id` 用于解析当前 API 账号。

- [Create Model](https://docs.fish.audio/api-reference/endpoint/model/create-model)：`POST /model`；普通文件上传使用 multipart；私有 fast；返回 `_id` 与 `state`。
- [Get Model](https://docs.fish.audio/api-reference/endpoint/model/get-model)：读取指定音色。
- [Voice Cloning](https://docs.fish.audio/features/voice-cloning)：持久音色 ID 可作为 TTS `reference_id` 使用。
- [Pricing & Rate Limits](https://docs.fish.audio/developer-guide/models-pricing/pricing-and-rate-limits)：当前列有 `s2.1-pro-free`；未据此推定克隆免费。
