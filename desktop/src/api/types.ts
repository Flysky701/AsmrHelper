// ── Health ─────────────────────────────────────────────
export interface HealthResponse {
  status: string
  version: string
}

// ── Tasks ──────────────────────────────────────────────
export type TaskState = 'pending' | 'running' | 'completed' | 'failed'

export interface TaskStatusResponse {
  task_id: string
  state: TaskState
  progress: number
  message: string
  detail: string
}

export interface TaskListResponse {
  tasks: TaskStatusResponse[]
}

// ── Pipeline ───────────────────────────────────────────
export interface PipelineRunRequest {
  input_path: string
  output_dir?: string
  vtt_path?: string | null
  source_lang?: string
  target_lang?: string
  use_vocal_separator?: boolean
  tts_engine?: string
  tts_voice?: string
  vocal_model?: string
  asr_model?: string
  translate_provider?: string
  tts_speed?: number
  original_volume?: number
  tts_volume_ratio?: number
  tts_delay?: number
  skip_existing?: boolean
  voice_profile_id?: string | null
}

export interface ArtifactSetResponse {
  files: Record<string, string>
  primary_output: string | null
}

export interface PipelineRunResponse {
  success: boolean
  input_path: string
  task: TaskStatusResponse | null
  task_id: string | null
  task_state: string | null
  artifacts: ArtifactSetResponse
  mix_path: string | null
  exported_subtitle: string | null
  total_duration: number
  error_message: string | null
}

export interface PipelinePresetsResponse {
  presets: string[]
}

export interface BatchPipelineRequest {
  input_files?: string[]
  input_dir?: string
  output_base_dir?: string
  source_lang?: string
  target_lang?: string
  use_vocal_separator?: boolean
  tts_engine?: string
  tts_voice?: string
  vocal_model?: string
  asr_model?: string
  translate_provider?: string
  tts_speed?: number
  original_volume?: number
  tts_volume_ratio?: number
  tts_delay?: number
  skip_existing?: boolean
  max_workers?: number
  use_batch_output_structure?: boolean
  voice_profile_id?: string | null
}

export interface BatchItemResultResponse {
  file: string
  status: string
  output: string | null
  error: string | null
  duration: number
}

export interface BatchPipelineResponse {
  items: BatchItemResultResponse[]
  total_count: number
  success_count: number
  skipped_count: number
  failed_count: number
  total_duration: number
}

// ── ASR ────────────────────────────────────────────────
export interface TranscribeRequest {
  input_path: string
  output_path?: string | null
  model?: string
  language?: string
}

export interface TranscribeSegment {
  start: number
  end: number
  text: string
}

export interface TranscribeResponse {
  segments: TranscribeSegment[]
  output_path: string | null
  text: string
}

// ── Translation ────────────────────────────────────────
export interface TranslateRequest {
  input_path: string
  output_path?: string | null
  provider?: string
  source_lang?: string
  target_lang?: string
}

export interface TranslateResponse {
  items: string[]
  provider: string
  source_lang: string
  target_lang: string
}

// ── TTS ────────────────────────────────────────────────
export interface SynthesizeRequest {
  input_path: string
  output_path: string
  engine?: string
  voice?: string
}

export interface SynthesizeResponse {
  engine: string
  voice: string
  output_path: string
}

// ── Models ─────────────────────────────────────────────
export interface ModelSummaryResponse {
  model_id: string
  kind: string
  category: string
  backend: string
  display_name: string
}

export interface ModelStatusResponse {
  model_id: string
  status: string
  detail: string
}

export interface ModelOperationResponse {
  action: string
  model_id: string
  success: boolean
  status: string
  detail: string
}

export interface ModelInstallRequest {
  mirror?: string
  force?: boolean
}

export interface ModelVerificationResponse {
  model_id: string
  valid: boolean
  detail: string
}

// ── Subtitles ──────────────────────────────────────────
export interface SubtitleSegmentModel {
  start: number
  end: number
  text: string
}

export interface SubtitleDocumentModel {
  segments: SubtitleSegmentModel[]
}

export interface SubtitleLoadRequest {
  file_path: string
}

export interface SubtitleLoadResponse {
  document: SubtitleDocumentModel
  segments: SubtitleSegmentModel[]
}

export interface SubtitleExportRequest {
  document?: SubtitleDocumentModel
  segments?: SubtitleSegmentModel[]
  output_path: string
}

export interface SubtitleExportResponse {
  output_path: string
  segment_count: number
}

export interface ScriptToVttRequest {
  script_path: string
  output_path?: string
  audio_path?: string | null
  vtt_path?: string | null
  fmt?: string
  use_llm_clean?: boolean
  asr_model_size?: string
  asr_language?: string
  track_index?: number | null
  vertical_mode?: string
  debug_dir?: string | null
}

export interface ScriptToVttResponse {
  mode: string
  output_path: string | null
  text: string
  line_count: number
}

// ── Resources ──────────────────────────────────────────
export interface ResourceStatusResponse {
  name: string
  available: boolean
  detail: string
  metadata: Record<string, unknown>
}

export interface ResourceStatusListResponse {
  resources: ResourceStatusResponse[]
}

// ── Voice ──────────────────────────────────────────────
export interface VoiceProfileSummaryResponse {
  id: string
  name: string
  category: string
  engine: string
  description: string
  available: boolean
}

export interface VoiceProfileResponse {
  id: string
  name: string
  category: string
  engine: string
  description: string
  speaker: string
  instruct: string
  design_instruct: string
  ref_audio: string
  generated: boolean
  available: boolean
}

export interface VoiceDesignRequest {
  description: string
  name: string
  ref_text?: string
}

export interface VoiceDesignResponse {
  profile_id: string
  name: string
  category: string
  ref_audio_path: string
  prompt_cache_path: string
}

export interface VoiceCloneRequest {
  audio_path: string
  name: string
  ref_text?: string
}

export interface VoiceCloneResponse {
  profile_id: string
  name: string
  category: string
  ref_audio_path: string
  prompt_cache_path: string
}

export interface SegmentAnalyzeRequest {
  audio_path: string
  ref_text?: string
}

export interface SegmentInfo {
  start: number
  end: number
  text: string
  quality_score: number
}

export interface SegmentAnalyzeResponse {
  segments: SegmentInfo[]
  recommended_index: number
}

export interface VoicePreviewRequest {
  text: string
  speed?: number
}

export interface VoicePreviewResponse {
  profile_id: string
  audio_path: string
}

// ── Tools ──────────────────────────────────────────────
export interface SeparationRequest {
  input_path: string
  output_dir?: string
  model?: string
  stems?: string[]
}

export interface SeparationResponse {
  input_path: string
  stems: Record<string, string>
  primary_output: string | null
}

export interface ConvertRequest {
  input_path: string
  output_path: string
  target_format?: string
  sample_rate?: number
  channels?: number
}

export interface ConvertResponse {
  input_path: string
  output_path: string
  format: string
  sample_rate: number
  channels: number
  duration: number
}

export interface SplitRequest {
  audio_path: string
  subtitle_path: string
  output_dir: string
  padding?: number
}

export interface SplitSegmentResponse {
  index: number
  start: number
  end: number
  text: string
  output_path: string
}

export interface SplitResponse {
  audio_path: string
  subtitle_path: string
  segments: SplitSegmentResponse[]
  total_segments: number
}

export interface SubtitleTranslationRequest {
  input_path: string
  output_path?: string
  provider?: string
  source_lang?: string
  target_lang?: string
  bilingual?: boolean
}

export interface SubtitleTranslationResponse {
  input_path: string
  output_path: string | null
  total_segments: number
  provider: string
  source_lang: string
  target_lang: string
}

export interface VolumePreviewRequest {
  audio_path: string
  tts_path?: string | null
  original_volume?: number
  tts_volume_ratio?: number
}

export interface VolumePreviewResponse {
  audio_path: string
  rms_volume: number
  tts_rms_volume: number | null
  recommended_original_volume: number
  recommended_tts_ratio: number
}
