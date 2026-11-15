// The last resume used, remembered in THIS browser only (never sent to our server for storage),
// so returning users don't re-upload every time. Storage can be blocked or cleared at any
// moment (private windows, site-data settings), so every access is wrapped.

const KEY = 'resume-gap.saved-resume'

export interface SavedResume {
  text: string
  label: string // file name, or "pasted text"
  savedAt: string // ISO date
}

export function loadSavedResume(): SavedResume | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as SavedResume
    return typeof parsed?.text === 'string' && parsed.text.trim() ? parsed : null
  } catch {
    return null
  }
}

export function saveResume(text: string, label: string): SavedResume | null {
  const saved = { text, label, savedAt: new Date().toISOString() }
  try {
    localStorage.setItem(KEY, JSON.stringify(saved))
    return saved
  } catch {
    return null // storage unavailable: the resume still works for this visit
  }
}

export function forgetSavedResume(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    // nothing to forget
  }
}
