import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'
import {
  deleteDocument,
  getDocument,
  listDocuments,
  uploadFile,
  type DocumentDetail,
  type DocumentMeta,
} from '../api'
import { ErrorNotice, formatBytes, formatDate } from '../components'

export default function FilesView() {
  const [documents, setDocuments] = useState<DocumentMeta[]>([])
  const [selected, setSelected] = useState<DocumentDetail | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const load = useCallback(async () => {
    try {
      const res = await listDocuments()
      setDocuments(res.documents)
    } catch (err) {
      setError(err)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const handleUpload = async (file: File | undefined) => {
    if (!file) return
    setError(null)
    setUploading(true)
    try {
      await uploadFile(file)
      await load()
    } catch (err) {
      setError(err)
    } finally {
      setUploading(false)
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragOver(false)
    void handleUpload(e.dataTransfer.files?.[0])
  }

  const open = async (id: number) => {
    setError(null)
    try {
      setSelected(await getDocument(id))
    } catch (err) {
      setError(err)
    }
  }

  const remove = async (id: number) => {
    setError(null)
    try {
      await deleteDocument(id)
      if (selected?.id === id) setSelected(null)
      await load()
    } catch (err) {
      setError(err)
    }
  }

  return (
    <div className="view">
      <ErrorNotice error={error} />
      <div
        className={dragOver ? 'dropzone dropzone-over' : 'dropzone'}
        onDragOver={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
      >
        <p>
          {uploading
            ? 'Uploading & extracting text…'
            : 'Drop a file here or click to choose — PDF, DOCX, TXT or Markdown, max 20 MB.'}
        </p>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.txt,.md"
          hidden
          onChange={(e) => {
            void handleUpload(e.target.files?.[0])
            e.target.value = ''
          }}
        />
      </div>
      <p className="muted small">
        Documents are scoped to you: signed-in users see only their own uploads; guests share
        the anonymous scope.
      </p>

      {documents.length === 0 ? (
        <p className="muted">No documents yet.</p>
      ) : (
        <ul className="doc-list">
          {documents.map((d) => (
            <li key={d.id} className="doc-item">
              <button type="button" className="doc-open" onClick={() => void open(d.id)}>
                <span className="doc-name">📄 {d.filename}</span>
                <span className="muted small">
                  {formatBytes(d.size)} · {formatDate(d.created_at)}
                </span>
              </button>
              <button type="button" className="btn btn-small btn-danger" onClick={() => void remove(d.id)}>
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}

      {selected && (
        <div className="card">
          <h3>{selected.filename}</h3>
          <p className="muted small">
            {selected.mime} · {formatBytes(selected.size)}
            {selected.truncated && ' · preview truncated by the server'}
          </p>
          <pre className="doc-text">{selected.text}</pre>
        </div>
      )}
    </div>
  )
}
