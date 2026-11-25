import { useState } from 'react'
import { generateImage, type GeneratedImage } from '../api'
import { ErrorNotice } from '../components'

export default function ImagesView() {
  const [prompt, setPrompt] = useState('')
  const [model, setModel] = useState('')
  const [size, setSize] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [images, setImages] = useState<GeneratedImage[]>([])

  const submit = async () => {
    if (!prompt.trim() || busy) return
    setError(null)
    setBusy(true)
    try {
      const res = await generateImage(prompt.trim(), model, size)
      setImages(res.data ?? [])
      if (!res.data || res.data.length === 0) {
        setError(new Error('the gateway returned no images'))
      }
    } catch (err) {
      setError(err)
      setImages([])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="view">
      <form
        className="card form-card"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <label className="field">
          Image prompt
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={3}
            placeholder="Describe the image to generate…"
            required
          />
        </label>
        <div className="form-row">
          <label className="field">
            Model (optional — gateway default if empty)
            <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="e.g. dall-e-3" />
          </label>
          <label className="field">
            Size (optional)
            <input value={size} onChange={(e) => setSize(e.target.value)} placeholder="e.g. 1024x1024" />
          </label>
        </div>
        <button type="submit" className="btn btn-primary" disabled={busy || !prompt.trim()}>
          {busy ? 'Generating…' : 'Generate image'}
        </button>
      </form>

      <ErrorNotice error={error} />

      {images.length > 0 && (
        <div className="image-grid">
          {images.map((img, i) => {
            const src = img.url ?? (img.b64_json ? `data:image/png;base64,${img.b64_json}` : null)
            return (
              <figure key={i} className="card image-card">
                {src ? (
                  <img src={src} alt={img.revised_prompt ?? prompt} />
                ) : (
                  <p className="muted">The gateway returned an image entry with no URL or data.</p>
                )}
                {img.revised_prompt && (
                  <figcaption className="muted small">Revised prompt: {img.revised_prompt}</figcaption>
                )}
              </figure>
            )
          })}
        </div>
      )}
    </div>
  )
}
