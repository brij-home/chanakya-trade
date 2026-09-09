/**
 * utils/cleanText.js
 * ──────────────────
 * Institutional Text Hygiene & Universal Mojibake Sanitizer.
 * 
 * Holistic UTF-8 restoration system:
 * 1. Reconstructs corrupted UTF-8 byte streams misdecoded as Windows-1252 or ISO-8859-1
 *    (handles emojis, Greek letters like σ, math symbols, arrows, em-dashes).
 * 2. Secondary fallback replacement map for edge cases.
 * 3. Recursive payload sanitizer `sanitizeData(payload)` for end-to-end API hygiene.
 */

// Windows-1252 byte-to-character reverse map (0x80 to 0x9F)
const WIN1252_REVERSE = {
  0x20AC: 0x80, // €
  0x201A: 0x82, // ‚
  0x0192: 0x83, // ƒ
  0x201E: 0x84, // „
  0x2026: 0x85, // …
  0x2020: 0x86, // †
  0x2021: 0x87, // ‡
  0x02C6: 0x88, // ˆ
  0x2030: 0x89, // ‰
  0x0160: 0x8A, // Š
  0x2039: 0x8B, // ‹
  0x0152: 0x8C, // Œ
  0x017D: 0x8E, // Ž
  0x2018: 0x91, // ‘
  0x2019: 0x92, // ’
  0x201C: 0x93, // “
  0x201D: 0x94, // ”
  0x2022: 0x95, // •
  0x2013: 0x96, // –
  0x2014: 0x97, // —
  0x02DC: 0x98, // ˜
  0x2122: 0x99, // ™
  0x0161: 0x9A, // š
  0x203A: 0x9B, // ›
  0x0153: 0x9C, // œ
  0x017E: 0x9E, // ž
  0x0178: 0x9F, // Ÿ
}

// Regex matching contiguous runs of 2 or more Windows-1252 high-byte characters
const WIN1252_RUN_REGEX = /[\u00C0-\u00FF\u0152\u0153\u0160\u0161\u0178\u017D\u017E\u0192\u02C6\u02DC\u2013\u2014\u2018\u2019\u201A\u201C\u201D\u201E\u2020\u2021\u2022\u2026\u2030\u2039\u203A\u20AC\u2122]{2,}/g

// Explicit secondary replacement map for known patterns and standalone artifacts
const FALLBACK_REPLACEMENTS = [
  [/\u00cf\u0192/g, 'σ'], // Ïƒ -> σ (Simons Z-score standard deviation)
  [/\u00e2\u2020\u2019/g, '→'], // â†’ -> →
  [/\u00e2\u20ac\u00a2/g, '•'], // â€¢ -> •
  [/\u00e2\u0161\u00a0[\u00ef\u00b8\u008f]?/g, '⚠️'], // âš ï¸ -> ⚠️
  [/\u00e2\u2013\u00b2/g, '▲'], // â–² -> ▲
  [/\u00e2\u2013\u00bc/g, '▼'], // â–¼ -> ▼
  [/\u00e2\u009d\u0149/g, '❌'], // â Œ -> ❌
  [/\u00e2\u20ac\u201d/g, '—'], // â€” -> —
  [/\u00e2\u201d\u20ac/g, '─'], // â”€ -> ─
  [/\u00e2\u0161\u00a1/g, '⚡'], // âš¡ -> ⚡
  [/\u00f0\u0178\u0161\u20ac/g, '🚀'], // ðŸš€ -> 🚀
  [/\u00f0\u0178\u2019\u017d/g, '💎'], // ðŸ’Ž -> 💎
  [/\u00f0\u0178\u203a\u00a1[\u00ef\u00b8\u008f]?/g, '🛡️'], // ðŸ›¡ï¸ -> 🛡️
  [/\u00f0\u0178\u201c\u02c6/g, '📈'], // ðŸ“ˆ -> 📈
  [/\u00f0\u0178\u017d\u00af/g, '🎯'], // ðŸŽ¯ -> 🎯
  [/\u00f0\u0178\u00a7\u00ae/g, '🧮'], // ðŸ§® -> 🧮
  [/\u00f0\u0178\u201a/g, '🐂'], // ðŸ‚ -> 🐂
  [/\u00f0\u0178\u00b0/g, '🏰'], // ðŸ° -> 🏰
  [/\u00f0\u0178\u201d/g, '🔍'], // ðŸ” -> 🔍
  [/\u00f0\u0178\u0152\u0160/g, '🌊'], // ðŸŒŠ -> 🌊
  [/\u00f0\u0178\u203a\u2019/g, '🛒'], // ðŸ›’ -> 🛒
  [/\u00f0\u0178\u203a[\u00ef\u00b8\u008f]?/g, '🏛️'], // ðŸ›ï¸ -> 🏛️
  [/\u00f0\u0178\u0152/g, '🌐'], // ðŸŒ -> 🌐
  [/\u00f0\u0178\u2014[\u00ef\u00b8\u008f]?/g, '🏗️'], // ðŸ—ï¸ -> 🏗️
  [/\u00f0\u0178\u00a2/g, '🏢'], // ðŸ¢ -> 🏢
]

/**
 * Sanitizes any string by:
 * 1. Reconstructing original UTF-8 bytes from Windows-1252 run sequences.
 * 2. Running secondary fallback replacements for edge cases.
 * @param {string} str - Raw string possibly containing encoding artifacts
 * @returns {string} Clean, authentic UTF-8 string
 */
export function cleanMojibake(str) {
  if (typeof str !== 'string' || !str) return str || ''

  // Pass 1: Universal Windows-1252 to UTF-8 Byte Reconstructor
  let cleaned = str.replace(WIN1252_RUN_REGEX, (match) => {
    const bytes = []
    for (let i = 0; i < match.length; i++) {
      const code = match.charCodeAt(i)
      if (WIN1252_REVERSE[code] !== undefined) {
        bytes.push(WIN1252_REVERSE[code])
      } else if (code <= 0xff) {
        bytes.push(code)
      } else {
        return match
      }
    }
    try {
      return new TextDecoder('utf-8', { fatal: true }).decode(new Uint8Array(bytes))
    } catch {
      return match
    }
  })

  // Pass 2: Secondary explicit replacements for isolated or edge-case sequences
  for (const [pattern, replacement] of FALLBACK_REPLACEMENTS) {
    cleaned = cleaned.replace(pattern, replacement)
  }

  return cleaned
}

/**
 * Recursively sanitizes any data payload (objects, arrays, strings)
 * ensuring zero mojibake can ever enter application state.
 * @param {any} data - Raw payload from API / store
 * @returns {any} Sanitized payload
 */
export function sanitizeData(data) {
  if (data == null) return data
  if (typeof data === 'string') return cleanMojibake(data)
  if (Array.isArray(data)) return data.map(sanitizeData)
  if (typeof data === 'object') {
    const out = {}
    for (const [k, v] of Object.entries(data)) {
      out[k] = sanitizeData(v)
    }
    return out
  }
  return data
}

/**
 * Cleans a council or persona title for display.
 * @param {string} name - Council name or title
 * @param {string} defaultIcon - Optional fallback icon
 * @returns {{ cleanName: string, icon: string }}
 */
export function sanitizeCouncilMeta(name, defaultIcon = '🏛️') {
  const cleaned = cleanMojibake(name || '')
  return {
    cleanName: cleaned.replace(/^[^\w\s]+/u, '').trim(),
    icon: cleanMojibake(defaultIcon),
  }
}
