import DraftReviewPanel from '@/components/tasks/DraftReviewPanel'
import SubtitleWorkshop from '@/pages/SubtitleWorkshop'
import { t, useI18n } from '@/i18n'
import { useNavStore } from '@/stores/navStore'
import './ReviewStudio.css'

export default function ReviewStudio() {
  useI18n()
  const reviewView = useNavStore((s) => s.reviewView)
  const openReview = useNavStore((s) => s.openReview)
  const pendingDraftCount = useNavStore((s) => s.pendingDraftCount)
  const setPage = useNavStore((s) => s.setPage)

  return (
    <div className="review-studio">
      <header className="page-heading app-page-heading subtitle-page-heading">
        <div className="page-heading__copy"><div className="page-title-row"><h1 className="page-title">{t('精修与字幕')}</h1></div></div>
        <div className="page-heading__actions">
          <div className="review-studio-switch" role="group" aria-label={t('精修与字幕')}>
            <button type="button" aria-pressed={reviewView === 'drafts'} onClick={() => void openReview('drafts')}>
              {t('草稿审校')}
              {pendingDraftCount > 0 && <span className="review-studio-count">{pendingDraftCount}</span>}
            </button>
            <button type="button" aria-pressed={reviewView === 'subtitles'} onClick={() => void openReview('subtitles')}>
              {t('字幕与台本')}
            </button>
          </div>
          {reviewView === 'drafts' && <button type="button" className="review-studio-new" onClick={() => void setPage('workbench')}>
            {t('＋ 新建草稿')}
          </button>}
        </div>
      </header>
      <div className="review-studio-body">
        {reviewView === 'drafts' ? <DraftReviewPanel /> : <SubtitleWorkshop />}
      </div>
    </div>
  )
}
