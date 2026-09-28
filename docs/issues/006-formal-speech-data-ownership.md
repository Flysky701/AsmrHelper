# 006：正式配音与试听数据归属

状态：已登记，待讨论；2026-09-28。用户要求本轮不修改。

## 已确认的现状

正式配音通过 `SpeechService.synthesize_timeline` 建立 plan、experiment、take、selection 等记录，与 VoiceLab 试听共用存储和音频目录。Pipeline 执行器直接调用应用层 SpeechService。

共同使用合成引擎和编译器是合理复用。需要评估的是：正式任务产物、声音库录音、试听候选分别由谁保存、备份和清理，避免处理一类数据时影响另一类。

## 后续讨论范围

1. 列清现有正式任务、试听和参考录音的保存与读取路径。
2. 确定是否只调整新任务的输出归属，历史数据保留原地可读。
3. 再决定是否需要注入独立合成接口；不先做整套服务拆分。

验收边界：已有音频不丢失，历史任务仍可读及按现有范围恢复；不重复实现引擎执行能力。

相关文件：`src/app/services/speech_service.py`、`src/core/speech/store.py`、`src/core/orchestration/pipeline/executor.py`。

混音附加记录错误隔离属于清单第 3 项，用户已跳过，不借本问题自动实施。
