import type { FishClone, FishCloneDraft, FishClonePreview } from '@/api/fishClones'

interface CloneApi {
  preview: (draft: FishCloneDraft) => Promise<FishClonePreview>
  create: (draft: FishCloneDraft, token: string, requestId: string) => Promise<FishClone>
}

/** One explicit action per draft. Only local preflight failures may be retried. */
export class FishCloneSubmission {
  private attempts = new Map<string, { promise: Promise<FishClone>; dispatched: boolean }>()
  constructor(private api: CloneApi, private uuid = () => crypto.randomUUID()) {}
  private key(draft: FishCloneDraft) { return JSON.stringify([draft.connection_ref, draft.asset_id, draft.title.trim()]) }
  dispatched(draft: FishCloneDraft) { return this.attempts.get(this.key(draft))?.dispatched || false }
  submit(draft: FishCloneDraft): Promise<FishClone> {
    const key = this.key(draft), existing = this.attempts.get(key)
    if (existing) return existing.promise
    const snapshot = { ...draft, title: draft.title.trim() }
    const attempt = { dispatched: false, promise: Promise.resolve(null as unknown as FishClone) }
    // Defer preflight until the entry exists, including synchronously throwing adapters.
    attempt.promise = Promise.resolve().then(async () => {
      const review = await this.api.preview(snapshot)
      const requestId = this.uuid()
      attempt.dispatched = true
      try { return await this.api.create(snapshot, review.token, requestId) }
      catch { throw new Error('创建响应未能确认；请刷新本地记录并到 Fish 核查，不要重复上传。') }
    }).catch(error => {
      if (!attempt.dispatched) this.attempts.delete(key)
      throw error
    })
    this.attempts.set(key, attempt)
    return attempt.promise
  }
}
