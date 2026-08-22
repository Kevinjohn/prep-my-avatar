export const SETUP_REDIRECT_SESSION_KEY = 'lds_setup_redirected'

export function readSession(key) {
  try {
    return window.sessionStorage.getItem(key)
  } catch {
    return null
  }
}

export function writeSession(key, value) {
  try {
    window.sessionStorage.setItem(key, value)
    return true
  } catch {
    return false
  }
}

export function removeSession(key) {
  try {
    window.sessionStorage.removeItem(key)
    return true
  } catch {
    return false
  }
}
