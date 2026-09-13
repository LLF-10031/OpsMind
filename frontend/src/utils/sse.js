export async function postEventStream(url, body, { onEvent, signal } = {}) {
  const token = localStorage.getItem('opsmind_token')
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    },
    body: JSON.stringify(body),
    signal
  })
  if (!res.ok || !res.body) {
    throw new Error(`HTTP ${res.status}`)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  const handleBlock = (block) => {
    const evt = { event: 'message', data: '', json: null }
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) evt.event = line.slice(6).trim()
      else if (line.startsWith('data:')) evt.data += line.slice(5).trim()
    }
    if (evt.data) {
      try {
        evt.json = JSON.parse(evt.data)
      } catch {
        evt.json = null
      }
    }
    if (evt.event === 'done') return false
    if (onEvent) onEvent(evt)
    return true
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      if (!handleBlock(block)) return
    }
  }
}
