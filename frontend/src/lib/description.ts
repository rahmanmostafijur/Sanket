/**
 * Turns a job description (plain text from the API, bullets as "- " lines) into renderable blocks.
 * It produces data only; React escapes every string, so nothing here can inject markup.
 */
export type DescriptionBlock =
  | { kind: 'p' | 'h'; text: string }
  | { kind: 'ul' | 'ol'; items: string[] }

const BULLET = /^[-•*–]\s+(.*)$/
const LONE_MARKER = /^[-•*–]$/
const NUMBERED = /^\d{1,2}[.)]\s+(.*)$/
const MAX_HEADING_LENGTH = 60

function withItem(blocks: DescriptionBlock[], kind: 'ul' | 'ol', item: string): DescriptionBlock[] {
  const last = blocks[blocks.length - 1]
  if (last?.kind === kind) return [...blocks.slice(0, -1), { kind, items: [...last.items, item] }]
  return [...blocks, { kind, items: [item] }]
}

function isHeading(line: string): boolean {
  return line.length <= MAX_HEADING_LENGTH && line.endsWith(':') && line.length > 1
}

/**
 * Paragraphs, "Heading:" lines, bullet lists and numbered lists. A bullet marker that sits alone on
 * its line (list items that wrapped their text in a paragraph) takes the next non-empty line.
 */
export function descriptionBlocks(text: string): DescriptionBlock[] {
  let blocks: DescriptionBlock[] = []
  let markerPending = false
  let paragraphBreak = true
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!line) {
      paragraphBreak = true
      continue
    }
    if (LONE_MARKER.test(line)) {
      markerPending = true
      continue
    }
    const bullet = BULLET.exec(line)
    const numbered = NUMBERED.exec(line)
    if (markerPending || bullet) {
      blocks = withItem(blocks, 'ul', markerPending ? line : (bullet?.[1] ?? line).trim())
      markerPending = false
    } else if (numbered) {
      blocks = withItem(blocks, 'ol', (numbered[1] ?? line).trim())
    } else if (isHeading(line)) {
      blocks = [...blocks, { kind: 'h', text: line.slice(0, -1).trim() }]
    } else {
      const last = blocks[blocks.length - 1]
      blocks =
        last?.kind === 'p' && !paragraphBreak
          ? [...blocks.slice(0, -1), { kind: 'p', text: `${last.text}\n${line}` }]
          : [...blocks, { kind: 'p', text: line }]
    }
    paragraphBreak = false
  }
  return blocks
}
