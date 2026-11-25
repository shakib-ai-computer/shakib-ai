import { useMemo } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

// Render Markdown to sanitized HTML. marked produces the HTML; DOMPurify
// strips anything dangerous before it reaches dangerouslySetInnerHTML —
// model output is untrusted content and is never injected raw.
export function Markdown({ text }: { text: string }) {
  const html = useMemo(() => {
    const raw = marked.parse(text ?? '', { async: false }) as string
    return DOMPurify.sanitize(raw)
  }, [text])
  return <div className="markdown" dangerouslySetInnerHTML={{ __html: html }} />
}

/** Rough plain-text version of Markdown, for speech synthesis. */
export function markdownToPlainText(md: string): string {
  return md
    .replace(/```[\s\S]*?```/g, ' code block omitted. ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^#{1,6}\s+/gm, '')
    .replace(/[*_]{1,3}([^*_]+)[*_]{1,3}/g, '$1')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/^\s*>\s?/gm, '')
    .replace(/\n{2,}/g, '. ')
    .trim()
}
