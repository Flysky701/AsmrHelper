# Fish 官方 Playground 实测

日期：2026-09-24。通过用户已登录的 Chrome，在 https://fish.audio/zh-CN/app/playground/ 操作。用户授权创建名为 Playground 的 API 密钥；创建流程完成后成功生成音频，未复制或保存密钥至项目。

模型：`s2.1-pro-free`（页面 S2.1 Pro Free）。官方音色：语彤 Yutong - Female Mandarin (Mainland)，reference_id `74c6aba5cbf94a15bbdc547ffce5cb38`。

共同文本：今天辛苦了。放松下来，慢慢呼吸，我会在这里陪着你。

| 条件 | 实测媒体时长 | 文件 |
| --- | ---: | --- |
| 无标签 | 5.172125 秒 | output/fish-official-exploration/normal.mp3 |
| 文本前加 [whisper] | 5.119938 秒 | output/fish-official-exploration/whisper.mp3 |

两次生成都返回不同的输出音频，浏览器媒体 readyState=4，并通过网站下载按钮下载，随后复制到上述目录。采用页面其他默认参数，没有充值或购买套餐，没有上传本地音频。

结论：官方账号、Playground 与免费模型短句生成链路已跑通。此次不是第三方 fishaudio.org 测试，也不是本地 S2 Pro 权重测试。尚未主观听评、进行转录准确性检查或验证长句稳定性；标签是否产生自然耳语以及是否优于 VoxCPM，需试听确认。不同模型间音色不同，跨模型对比存在音色因素。

## ASMR 专用音色对照

同日用户反馈语彤两版差异不明显后，在中文社区音色中选择 ASMR（作者小温），reference_id 为 `182fc90734744f7894273368e9b6bb29`。模型仍为 `s2.1-pro-free`，相同中文文本，其余页面默认参数，没有后期降速、降音量或空间处理。

| 条件 | 浏览器媒体时长 | 文件 |
| --- | ---: | --- |
| ASMR 音色，无标签 | 5.590125 秒 | output/fish-official-exploration/asmr-xiaowen-untagged.mp3 |
| ASMR 音色，前置 [whispering] | 5.720750 秒 | output/fish-official-exploration/asmr-xiaowen-whispering.mp3 |

两版返回独立音频且 readyState=4，均经网页下载并保存到项目。中间一次编辑器追加文本导致重复句子的生成已排除；最终耳语版本生成前核对了单句文本。这里验证的是专用音色能通过官方免费模型生成，不代表已经确认耳语音质或复现视频。需试听以上两版，并与此前语彤样本比较音色与标签分别带来的差别。
