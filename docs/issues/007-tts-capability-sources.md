# 007：TTS 能力描述与配置来源收口

状态：已登记，待讨论；2026-09-28。用户要求本轮不修改。

## “新旧两套”具体指什么

- 旧能力接口 `/capabilities` 仍由 `capability_descriptor_service.py` 读取 `external_tts` 等设置生成 TTS 描述；设置服务仍接受该配置的更新。
- 新语音功能使用 `/speech/providers` 的引擎能力声明，以及命名的 speech connection。
- 两套描述/配置并存，不等于两套合成链路都在执行。旧 `/tts`、`/voice` HTTP 入口已退出挂载；当前主流程和试听共用新合成能力。

2026-09-29 架构图核对补充：`src/cli.py` 中的 `tts` 命令仍调用 `TtsEngineService.synthesize_file`，经 `ExecutionProfileBuilder` 和 `RuntimeRouter` 执行。因而“旧 HTTP 入口关闭”不代表旧执行服务已完全停用。桌面路径已统一，命令行仍有旧路径；此次为代码调用确认，未运行真实合成。讨论旧接口收口时必须包含 CLI，不能直接删除旧服务。

## 待决定的问题

1. 哪些页面、脚本或现有配置仍实际依赖旧描述？先列调用方。
2. 旧接口应保留为新目录的兼容投影，还是在没有调用方后移除？
3. 旧保存配置是否需要显式导入，如何避免覆盖命名服务与凭据？

验收边界：界面声明的能力与实际执行一致；用户配置不静默迁移或丢失；不恢复旧执行入口，不扩大引擎支持范围。

相关文件：`src/app/services/capability_descriptor_service.py`、`src/app/services/settings_service.py`、`src/core/speech/providers.py`、`src/api/http/app.py`。
