/** Render familiar filesystem paths without changing stored or executable values. */
export function displayPath(path: string): string {
  if (/^\\\\\?\\UNC\\[^\\]+\\[^\\]+(?:\\|$)/i.test(path)) {
    return `\\\\${path.slice(8)}`
  }
  if (/^\\\\\?\\[a-z]:\\/i.test(path)) return path.slice(4)
  return path
}
