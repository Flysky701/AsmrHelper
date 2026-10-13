import { t, useI18n } from '@/i18n'
import type { SpeechProvider, SpeechRecipe } from '@/api/speech'
import './VoiceRecipeList.css'

export interface VoiceRecipeListProps {
  recipes: SpeechRecipe[]
  providers: SpeechProvider[]
  selectedId: string
  onSelect: (recipe: SpeechRecipe) => void
  onAudition?: (recipe: SpeechRecipe) => void
  onRemove?: (recipe: SpeechRecipe) => void
  disabled?: boolean
}

const modelNames: Record<string, string> = {
  'qwen3-base': 'Qwen3 Base',
  'qwen3-custom-voice': 'Qwen3 CustomVoice',
  'qwen3-voice-design': 'Qwen3 VoiceDesign',
  voxcpm2: 'VoxCPM2',
}
const modeNames: Record<string, string> = {
  default: '默认声音', hosted: '服务端音色', builtin: '内置声音', reference: '参考音频', design: '声音设计',
}

/** Selection and draft protection stay with the parent; this list only presents saved recipes. */
export default function VoiceRecipeList({ recipes, providers, selectedId, onSelect, onAudition, onRemove, disabled }: VoiceRecipeListProps) {
  useI18n()
  return <div className="voice-list voice-recipe-list" role="list" aria-label={t("音色列表")}>
    {recipes.map(recipe => {
      const provider = providers.find(provider => provider.provider_id === recipe.provider_id)
      const providerName = provider?.name || recipe.provider_id
      const modelName = modelNames[recipe.model] || recipe.model || providerName || t('模型未记录')
      const modeName = modeNames[recipe.mode] ? t(modeNames[recipe.mode] || recipe.mode) : recipe.mode || t('方式未记录')
      const description = [providerName, recipe.model, modeName].filter(Boolean).join(' · ')
      return <div className="voice-recipe-entry" role="listitem" key={recipe.id} aria-label={recipe.name} data-selected={recipe.id === selectedId ? 'true' : undefined}>
        <button type="button" className="voice-recipe-row" disabled={disabled} title={recipe.name} aria-label={recipe.name}
          aria-current={recipe.id === selectedId ? 'true' : undefined} onClick={() => onSelect(recipe)}>
          <span className="voice-recipe-heading"><strong title={recipe.name}>{recipe.name}</strong>
            {recipe.archived && <span className="voice-recipe-archived">{t("旧版保留项")}</span>}
          </span>
          <span className="voice-recipe-source">{recipe.variant.kind === 'hosted' ? t('云端 ID') : provider?.remote === false ? t('本地引擎') : provider?.remote ? t('远程引擎') : t('声音预设')}</span>
          <span className="voice-recipe-description" title={description}>
            <span className="voice-recipe-model">{modelName}</span><span className="voice-recipe-separator" aria-hidden="true">·</span><span className="voice-recipe-mode">{t(modeName)}</span>
          </span>
        </button>
        {(onAudition || onRemove) && <div className="voice-recipe-actions">
          <button type="button" disabled={disabled} onClick={() => onSelect(recipe)}>{t("编辑")}</button>
          {onAudition && <button type="button" disabled={disabled || recipe.archived} onClick={() => onAudition(recipe)}>{t("试听")}</button>}
          {onRemove && <button type="button" disabled={disabled} onClick={() => onRemove(recipe)}>{t("删除")}</button>}
        </div>}
      </div>
    })}
  </div>
}
