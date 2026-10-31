export function splitAssistantTaskReply(reply) {
  const text = String(reply || '').trim()
  const heading = text.match(/^#{1,3}[ \t]+结论[：:][ \t]*([^\r\n]*)(?:\r?\n|$)/)
  if (!heading) return { conclusion: null, details: text }
  return { conclusion: heading[1].trim(), details: text.slice(heading[0].length).trim() }
}
