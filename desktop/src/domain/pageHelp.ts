import modelReadiness from '../../../docs/guides/model-readiness.md?raw'
import doc0 from '../../../docs/guides/workbench.md?raw'
import doc1 from '../../../docs/guides/workflow-graph-v2.md?raw'
import doc2 from '../../../docs/guides/cloud-tts-user-guide.md?raw'
import doc3 from '../../../docs/guides/voice-lab-v2.md?raw'
import doc4 from '../../../docs/guides/fish-cloning.md?raw'
import doc5 from '../../../docs/guides/reference-selection.md?raw'
import doc6 from '../../../docs/guides/tts.md?raw'
import doc7 from '../../../docs/guides/quick-start.md?raw'
import doc8 from '../../../docs/guides/installation.md?raw'
import doc9 from '../../../docs/guides/desktop-page-help.md?raw'
import extensionDoc from '../../../docs/cloud-tts-extension.md?raw'

export const HELP_DOCUMENTS: Record<string, string> = {
  'model-readiness.md': modelReadiness,
  'workbench.md': doc0,
  'workflow-graph-v2.md': doc1,
  'cloud-tts-user-guide.md': doc2,
  'voice-lab-v2.md': doc3,
  'fish-cloning.md': doc4,
  'reference-selection.md': doc5,
  'tts.md': doc6,
  'quick-start.md': doc7,
  'installation.md': doc8,
  'desktop-page-help.md': doc9,
  '../cloud-tts-extension.md': extensionDoc,
}

export function resolveHelpDocument(reference: string): { reference: string; source: string } | null {
  const [file, encodedSection] = reference.split('#', 2)
  const source = HELP_DOCUMENTS[file || ""]
  if (!source) return null
  if (!encodedSection) return { reference, source }
  let section: string
  try { section = decodeURIComponent(encodedSection) } catch { return null }
  const lines = source.split(/\r?\n/)
  const start = lines.findIndex(line => /^#{1,6} /.test(line) && line.replace(/^#{1,6} /, '') === section)
  if (start < 0) return null
  const level = lines[start]!.match(/^#+/)![0].length
  let end = start + 1
  while (end < lines.length && !(new RegExp(`^#{1,${level}} `)).test(lines[end]!)) end++
  return { reference, source: lines.slice(start, end).join('\n') }
}

export const PAGE_HELP = {
  "workbench": {"title": "工作台", "document": "workbench.md", "steps": [{"title": "选择流水线", "detail": "选择已保存的流水线，先用默认参数。"}, {"title": "导入素材并补齐输入", "detail": "导入素材，展开素材组并补齐必需输入。"}, {"title": "按需调整参数", "detail": "需要时打开调整参数，修改对应模块设置。"}, {"title": "开始处理", "detail": "勾选要处理的素材组，再提交运行。"}, {"title": "查看结果", "detail": "在任务中心查看进度、错误和产物。"}]},
  "workflow": { title: "流水线编辑器", document: "workflow-graph-v2.md", steps: [{"title": "打开或新建流程", "detail": "选择已保存流水线并打开编辑，或新建独立草稿。"}, {"title": "连接模块", "detail": "添加处理节点，连接输入与输出端口，并定义需要绑定的素材槽位。"}, {"title": "检查并保存", "detail": "检查节点参数及流程问题，命名后保存；内置模板保存为副本。"}, {"title": "在工作台运行", "detail": "返回工作台选择已保存流程，绑定素材后明确提交。"}] },
  "connections": { title: "外部服务", document: "desktop-page-help.md#外部服务", steps: [{"title": "添加服务连接", "detail": "按用途选择外部语言模型或语音合成区域，新增相应服务。"}, {"title": "填写连接信息", "detail": "填写名称、协议、地址和密钥；语音模型与声音在音色页选择。"}, {"title": "保存并检查", "detail": "保存连接。检查配置只校验字段；模型查询与连接测试可能访问服务。"}, {"title": "在对应模块使用", "detail": "翻译等节点选择语言模型连接；音色预设选择语音连接后保存。"}] },
  "presets": { title: "音色预设", document: "desktop-page-help.md#音色预设", steps: [{"title": "制作新音色", "detail": "填写名称与合成目标语言，选择引擎、模型和声音来源。"}, {"title": "准备声音来源", "detail": "按所选方式填写声音 ID、描述或参考素材；只填写该引擎支持的字段。"}, {"title": "配置连接与参数", "detail": "选择已保存的外部连接或本机设置，需要时展开高级连接设置。"}, {"title": "保存并复用", "detail": "保存到音色库，之后可在试听页载入，或在工作台语音合成节点选择。"}] },
  "audition": { title: "试听与记录", document: "desktop-page-help.md#试听与记录", steps: [{"title": "载入已保存预设", "detail": "选择要试听的音色，核对引擎、模型和目标语言。"}, {"title": "输入短句试音", "detail": "填写试音原文，明确点击生成试音后等待结果。"}, {"title": "播放并微调", "detail": "播放候选；高级选项中每次只改一个参数，再生成比较。"}, {"title": "保存候选设置", "detail": "满意候选点另存为音色预设，命名后保存所选结果的设置。"}] },
  "references": { title: "参考素材", document: "voice-lab-v2.md#声音库", steps: [{"title": "导入参考录音", "detail": "选择本机音频或上传文件，在列表中打开录音。"}, {"title": "试听并选段", "detail": "试听整段或框选范围；可加载字幕辅助定位，识别需明确提交。"}, {"title": "核对录音信息", "detail": "填写名称、语言及选段原文；确认文字与实际录音一致。"}, {"title": "另存并创建音色", "detail": "保存片段后用此录音创建音色；处理后的片段另存，原音频保留。"}] },
  "fish-clone": { title: "Fish 远程克隆", document: "fish-cloning.md", steps: [{"title": "准备连接和素材", "detail": "选择官方 Fish 连接与已保存的 WAV 参考片段，核对原文。"}, {"title": "检查上传摘要", "detail": "填写音色名称，确认上传片段与原文；仅使用有权克隆的素材。"}, {"title": "明确提交并查状态", "detail": "上传片段并创建音色可能计费；结果未知时先核查，不重复上传。"}, {"title": "就绪后保存音色", "detail": "状态为 trained 后保存为 Free 合成音色，之后手动试听或在工作台选用。"}] },
  "tasks": { title: "任务记录", document: "desktop-page-help.md#任务记录", steps: [{"title": "筛选任务", "detail": "按分类、状态或名称定位任务，选择一项打开详情。"}, {"title": "查看进度与错误", "detail": "查看阶段、日志和失败原因；刷新任务状态只更新记录。"}, {"title": "检查运行产物", "detail": "在详情的产物中播放或查看文件，并复制路径定位结果。"}, {"title": "按需处理记录", "detail": "取消和重试需明确操作；重试沿用原任务快照，删除前查看确认范围。"}] },
  "batches": { title: "批次管理", document: "desktop-page-help.md#批次管理", steps: [{"title": "选择批次", "detail": "打开已提交批次，查看各素材组的任务与状态。"}, {"title": "检查冻结设置", "detail": "查看提交时的流程和输入快照，避免把后来修改当作本批次设置。"}, {"title": "查看结果或恢复", "detail": "查看已完成组产物；失败或中断按界面提供的恢复操作处理。"}, {"title": "核对后再重试", "detail": "确认待处理范围与原配置后再提交，云端操作先核对已有结果。"}] },
  "subtitle-editor": { title: "字幕编辑", document: "desktop-page-help.md#字幕编辑", steps: [{"title": "加载字幕", "detail": "加载 SRT、VTT 或 LRC；需要试听定位时选择对应音频。"}, {"title": "编辑字幕行", "detail": "检查起止时间与原文，编辑所需行；选择行可定位预览。"}, {"title": "导出修改", "detail": "选择导出格式并保存字幕；离开前保留需要的修改。"}] },
  "subtitle-translate": { title: "字幕翻译", document: "desktop-page-help.md#字幕翻译", steps: [{"title": "准备字幕与连接", "detail": "浏览并选择字幕文件，在翻译服务中选择 DeepSeek 或 OpenAI。"}, {"title": "设置翻译方向", "detail": "核对源语言、目标语言、双语字幕选项及可选输出路径。"}, {"title": "提交并导出", "detail": "明确开始翻译，在任务中心查看进度和输出字幕；云端服务可能计费。"}] },
  "script-text": {"title": "台本转字幕：整理台词", "document": "desktop-page-help.md#台本转字幕：整理台词", "steps": [{"title": "准备台本", "detail": "选择 PDF 或 UTF-8 TXT；整理台词不需要录音。"}, {"title": "预览并确认", "detail": "预览台词和排除的动作说明，修订每行台词后确认；章节选项来自台本。"}, {"title": "保存台词文本", "detail": "提交后输出 TXT，不生成字幕时间轴。LLM 清洗默认关闭，启用会发送文本。"}]},
  "script-audio": {"title": "台本转字幕：录音匹配", "document": "desktop-page-help.md#台本转字幕：录音匹配", "steps": [{"title": "准备台本与录音", "detail": "选择对应录音、原文台本和录音语言；ASR 使用已安装的本地模型。"}, {"title": "预览并确认", "detail": "预览、修订台词与动作说明，再确认台词和录音一致；可选择台本章节。"}, {"title": "匹配并核对", "detail": "提交后在本页查看匹配、未匹配、额外录音和冲突；时间来自识别片段，不是逐字强制对齐。"}, {"title": "试听修正再导出", "detail": "载入编辑器试听，修改时间或手动插入台词；待核对稿确认后导出，重试保留旧结果。"}]},
  "script-vtt": {"title": "台本转字幕：复用原文字幕", "document": "desktop-page-help.md#台本转字幕：复用原文字幕", "steps": [{"title": "准备原文字幕与录音", "detail": "选择台本、对应录音和原文 SRT/VTT，确认字幕为该录音的同语言原文，不能使用译文。"}, {"title": "预览并确认", "detail": "预览、修订确认台词；参考字幕提供真实片段锚点并跳过 ASR。"}, {"title": "核对后导出", "detail": "在本页核对匹配结果，载入编辑器试听修正；未匹配台词没有时间，不自动插入。"}]},
  "audio-separate": { title: "人声分离", document: "desktop-page-help.md#人声分离", steps: [{"title": "选择输入音频", "detail": "选择需要分离的人声与背景混合音频。"}, {"title": "确认输出位置", "detail": "检查输出目录和工具可用状态，留空按当前默认目录输出。"}, {"title": "运行并试听结果", "detail": "提交后在任务中心查看分离任务，播放已登记的产物。"}] },
  "audio-convert": { title: "格式转换", document: "desktop-page-help.md#格式转换", steps: [{"title": "选择输入音频", "detail": "选择要转换的本机音频。"}, {"title": "设置输出格式", "detail": "检查格式、采样率、声道和输出路径。"}, {"title": "提交并查看文件", "detail": "运行后到任务中心查看结果与文件位置。"}] },
  "audio-split": { title: "按字幕切分", document: "desktop-page-help.md#按字幕切分", steps: [{"title": "准备音频与字幕", "detail": "选择音频及时间轴对应的字幕。"}, {"title": "设置切分参数", "detail": "核对前后留白与输出目录，避免使用不对应的时间轴。"}, {"title": "提交并查看片段", "detail": "到任务中心查看切分结果及各片段文件。"}] },
  "audio-translate": { title: "字幕翻译工具", document: "desktop-page-help.md#字幕翻译工具", steps: [{"title": "选择字幕文件", "detail": "选择需要翻译的时间轴字幕。"}, {"title": "设置语言方向", "detail": "检查原语言和目标语言；服务连接沿用工具当前配置。"}, {"title": "运行并查看译文", "detail": "提交后在任务中心查看结果，核对译文与时间轴。"}] },
  "audio-volume": { title: "音量分析", document: "desktop-page-help.md#音量分析", steps: [{"title": "选择分析音频", "detail": "选择原音频，按需提供配音文件。"}, {"title": "核对混音比例", "detail": "检查原音量与配音比例，用于计算分析建议。"}, {"title": "查看分析结果", "detail": "运行后查看任务详情中的 RMS 与混音建议，分析不替代实际听感核对。"}] },
  "appearance": { title: "外观与语言", document: "desktop-page-help.md#外观与语言", steps: [{"title": "选择界面语言", "detail": "切换中文或英文，素材、音色和模板名称保持原样。"}, {"title": "调整背景", "detail": "选择本机背景图片，调整遮罩；图片副本保存在本机。"}, {"title": "查看即时效果", "detail": "设置即时生效并自动保存；需要时恢复默认背景。"}] },
  "preset-catalog": { title: "预设管理：当前目录", document: "desktop-page-help.md#预设管理：当前目录", steps: [{"title": "选择流水线", "detail": "搜索并选择当前目录中已保存的流水线。"}, {"title": "维护流程", "detail": "打开编辑或创建副本；修改后在编辑器明确保存。"}, {"title": "确认删除范围", "detail": "删除前检查确认说明；已有任务使用自己的提交快照。"}] },
  "preset-templates": { title: "预设管理：内置模板", document: "desktop-page-help.md#预设管理：内置模板", steps: [{"title": "打开内置模板", "detail": "在添加内置模板目录中查看可用流程。"}, {"title": "添加独立副本", "detail": "选择模板并命名，每次添加都生成独立预设。"}, {"title": "编辑后再运行", "detail": "在当前目录打开新副本，保存设置后到工作台选用。"}] },
  "paths": { title: "文件与缓存", document: "desktop-page-help.md#文件与缓存", steps: [{"title": "核对工作区", "detail": "查看当前工作区；切换前保存草稿并确认没有正在运行的任务。"}, {"title": "调整存储路径", "detail": "设置输出、模型或临时目录；留空使用工作区默认位置。"}, {"title": "保存路径设置", "detail": "明确保存修改；路径设置不自动搬移已有文件。"}] },
  "local-asr": { title: "ASR 识别模型", document: "desktop-page-help.md#ASR 识别模型", steps: [{"title": "查看本分类模型", "detail": "在本地模型的 ASR 分类查看所需引擎与资源。"}, {"title": "查看资源状态", "detail": "核对权重、运行环境和模型目录；已配置不等于推理验证通过。"}, {"title": "按需验证资源", "detail": "使用验证查看问题；安装、修复或移除前确认作用对象。"}, {"title": "回到使用页面", "detail": "在工作台或对应工具选择已准备好的引擎，提交前核对参数。"}] },
  "local-tts": { title: "TTS 合成模型", document: "desktop-page-help.md#TTS 合成模型", steps: [{"title": "查看本分类模型", "detail": "在本地模型的 TTS 分类查看所需引擎与资源。"}, {"title": "查看资源状态", "detail": "核对权重、运行环境和模型目录；已配置不等于推理验证通过。"}, {"title": "按需验证资源", "detail": "使用验证查看问题；安装、修复或移除前确认作用对象。"}, {"title": "回到使用页面", "detail": "在工作台或对应工具选择已准备好的引擎，提交前核对参数。"}] },
  "local-llm": { title: "LLM 语言模型", document: "desktop-page-help.md#LLM 语言模型", steps: [{"title": "查看本分类模型", "detail": "在本地模型的 LLM 分类查看所需引擎与资源。"}, {"title": "查看资源状态", "detail": "核对权重、运行环境和模型目录；已配置不等于推理验证通过。"}, {"title": "按需验证资源", "detail": "使用验证查看问题；安装、修复或移除前确认作用对象。"}, {"title": "回到使用页面", "detail": "在工作台或对应工具选择已准备好的引擎，提交前核对参数。"}] },
  "local-other": { title: "其他资源", document: "desktop-page-help.md#其他资源", steps: [{"title": "查看本分类模型", "detail": "在本地模型的 其他 分类查看所需引擎与资源。"}, {"title": "查看资源状态", "detail": "核对权重、运行环境和模型目录；已配置不等于推理验证通过。"}, {"title": "按需验证资源", "detail": "使用验证查看问题；安装、修复或移除前确认作用对象。"}, {"title": "回到使用页面", "detail": "在工作台或对应工具选择已准备好的引擎，提交前核对参数。"}] },
  "workbench-common": {"title": "工作台：常用参数", "document": "workbench.md", "steps": [{"title": "选择流水线", "detail": "选择已保存流水线，确认输入槽位、处理节点和产出。"}, {"title": "导入并绑定素材", "detail": "导入音频或字幕，展开素材组，绑定必需输入并确认实际语言。"}, {"title": "工作台：常用参数", "detail": "检查各模块的引擎、音色、语言和连接；这些修改用于本次运行。"}, {"title": "开始处理", "detail": "勾选要处理的素材组，再提交运行。"}, {"title": "查看结果", "detail": "在任务中心查看进度、错误和产物。"}]},
  "workbench-advanced": {"title": "工作台：高级参数", "document": "workbench.md", "steps": [{"title": "选择流水线", "detail": "选择已保存流水线，确认输入槽位、处理节点和产出。"}, {"title": "导入并绑定素材", "detail": "导入音频或字幕，展开素材组，绑定必需输入并确认实际语言。"}, {"title": "工作台：高级参数", "detail": "仅调整当前模块显示的高级选项，并检查输出；不支持的参数不会提供。"}, {"title": "开始处理", "detail": "勾选要处理的素材组，再提交运行。"}, {"title": "查看结果", "detail": "在任务中心查看进度、错误和产物。"}]},
} satisfies Record<string, { title: string; document: string; steps: { title: string; detail: string }[] }>
export type PageHelpTopic = keyof typeof PAGE_HELP

// Public examples only. Help never reads connections, credentials or user media.
export const SERVICE_ADDRESSES = [
  { label: 'Fish Audio', value: 'https://api.fish.audio/v1' },
  { label: 'Gemini TTS', value: 'https://generativelanguage.googleapis.com/v1beta' },
  { label: 'ElevenLabs', value: 'https://api.elevenlabs.io' },
  { label: 'MiMo TTS', value: 'https://api.xiaomimimo.com/v1' },
]
export const VOICE_STARTERS = [
  { label: 'Fish Audio', model: 's2.1-pro-free', voice: '已有 Voice ID；可查询或手填' },
  { label: 'Gemini TTS', model: 'gemini-3.8-flash-tts', voice: 'Kore' },
  { label: 'ElevenLabs', model: 'eleven_v3', voice: '自己的真实 Voice ID' },
  { label: 'MiMo TTS', model: 'mimo-v2.5-tts', voice: 'mimo_default' },
]
export const AUDITION_EXAMPLE = '欢迎使用。放松下来，听一听这段中文配音。'
