import { useRef, useState, type DragEvent } from 'react'
import { ApiError, MAX_INPUT_CHARS, parseResumePdf } from '../api'

const REMOVED_ORDER = ['name', 'email', 'phone', 'location', 'link']

function describeRemoved(removed: string[]): string {
  return REMOVED_ORDER.filter((k) => removed.includes(k))
    .map((k) => {
      const n = removed.filter((r) => r === k).length
      return n === 1 ? k : `${n} ${k}s`
    })
    .join(', ')
}

/** Resume input that stays out of the way: a dropzone when empty, a one-line card once loaded,
 *  and the full text box only when the user asks to see or edit the text. */
export function ResumeInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [editing, setEditing] = useState(false)
  const [note, setNote] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const [dragging, setDragging] = useState(false)

  async function upload(file: File) {
    if (!file.name.toLowerCase().endsWith('.pdf') && file.type !== 'application/pdf') {
      setNote({ kind: 'error', text: 'Please choose a PDF file.' })
      return
    }
    setUploading(true)
    setNote(null)
    try {
      const parsed = await parseResumePdf(file)
      onChange(parsed.text)
      setEditing(false)
      const removed = describeRemoved(parsed.removed)
      setNote({
        kind: 'ok',
        text: removed ? `Loaded ${file.name}. Removed your ${removed}.` : `Loaded ${file.name}.`,
      })
    } catch (err) {
      setNote({ kind: 'error', text: err instanceof ApiError ? err.message : 'Upload failed. Please try again.' })
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = '' // allow re-uploading the same file
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) void upload(file)
  }

  const over = value.length > MAX_INPUT_CHARS
  const hasText = value.trim() !== ''
  const fileInput = (
    <input
      ref={fileRef}
      type="file"
      accept="application/pdf,.pdf"
      hidden
      onChange={(e) => {
        const file = e.target.files?.[0]
        if (file) void upload(file)
      }}
    />
  )

  return (
    <div className="textbox">
      <div className="textbox-label">
        <span>Your resume</span>
        {(editing || over) && (
          <span className={`counter ${over ? 'over' : ''}`}>
            {value.length.toLocaleString()} / {MAX_INPUT_CHARS.toLocaleString()}
          </span>
        )}
      </div>
      {fileInput}

      {hasText && !editing ? (
        <div className="resume-ready">
          <div>
            <p className="resume-ready-title">✓ Resume ready</p>
            <p className="muted small">
              {value.length.toLocaleString()} characters{over && ' (too long)'}
            </p>
          </div>
          <div className="resume-ready-actions">
            <button type="button" className="button-small" onClick={() => setEditing(true)}>
              View / edit
            </button>
            <button type="button" className="button-small" onClick={() => fileRef.current?.click()} disabled={uploading}>
              {uploading ? 'Reading…' : 'Replace PDF'}
            </button>
            <button
              type="button"
              className="button-small"
              onClick={() => {
                onChange('')
                setNote(null)
              }}
            >
              Clear
            </button>
          </div>
        </div>
      ) : (
        <>
          {!editing && (
            <button
              type="button"
              className={`dropzone ${dragging ? 'dragging' : ''}`}
              onClick={() => fileRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault()
                setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              disabled={uploading}
            >
              {uploading ? 'Reading PDF…' : 'Upload PDF or drop it here'}
            </button>
          )}
          {editing ? (
            <>
              <textarea
                aria-label="Resume text"
                value={value}
                onChange={(e) => onChange(e.target.value)}
                placeholder="Paste your resume as plain text"
                rows={10}
                autoFocus
              />
              <button type="button" className="button-link" onClick={() => setEditing(false)}>
                {hasText ? 'Done' : 'Cancel'}
              </button>
            </>
          ) : (
            <button type="button" className="button-link" onClick={() => setEditing(true)}>
              or paste text instead
            </button>
          )}
        </>
      )}

      {note && <p className={`upload-note ${note.kind}`}>{note.text}</p>}
    </div>
  )
}
