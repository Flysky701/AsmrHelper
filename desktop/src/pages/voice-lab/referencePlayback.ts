export function playbackBoundary(currentTime: number, range: { start: number; end: number }, loop: boolean, playing: boolean) {
  if (!Number.isFinite(range.start) || !Number.isFinite(range.end) || range.end <= range.start) return { pause: true }
  if (currentTime < range.start) return { pause: false, seek: range.start }
  if (currentTime >= range.end) return loop && playing ? { pause: false, seek: range.start } : { pause: true, seek: range.end }
  return { pause: false }
}

export type ClipIdentity = { path: string; start: number; end: number; language: string }
export function sameClip(a: ClipIdentity, b: ClipIdentity) {
  return a.path === b.path && a.start === b.start && a.end === b.end && a.language === b.language
}
