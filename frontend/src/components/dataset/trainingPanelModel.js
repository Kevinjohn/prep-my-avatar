export const CUSTOM_BASE_SENTINEL = '__custom_weights__'
export const DEFAULT_CUSTOM_FAMILIES = ['sdxl', 'krea', 'flux', 'flux2klein']
export const looksAbsolute = (path) => /^(?:[A-Za-z]:[\\/]|\\\\|\/)/.test(String(path || ''))
export const baseName = (path) => String(path || '').replace(/[\\/]+$/, '').split(/[\\/]/).pop() || String(path || '')
export const fmtBytes = (bytes) => {
  if (bytes == null) return ''
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`
  if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} MB`
  return `${Math.max(1, Math.round(bytes / 1e3))} KB`
}
