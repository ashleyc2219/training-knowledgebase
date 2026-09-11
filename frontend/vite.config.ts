import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv, type Plugin } from 'vite'

// Minimal dev-only proxy so the browser never touches the Anthropic API key.
// The frontend POSTs { prompt, max_tokens } to /api/generate; this plugin
// runs inside Vite's own Node process (no second server to manage) and
// makes the real Claude call server-side, key read from .env (gitignored).
// If no key is set, or the call fails, it returns a clear error the client
// falls back on — the demo never breaks, it just uses the template instead.
function claudeProxyPlugin(apiKey: string): Plugin {
  return {
    name: 'claude-proxy',
    configureServer(server) {
      server.middlewares.use('/api/generate', async (req, res) => {
        if (req.method !== 'POST') {
          res.statusCode = 405
          res.end('Method not allowed')
          return
        }
        if (!apiKey) {
          res.statusCode = 501
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify({ error: 'ANTHROPIC_API_KEY not set on the server' }))
          return
        }

        let body = ''
        for await (const chunk of req) body += chunk
        let prompt: string
        let maxTokens: number
        try {
          const parsed = JSON.parse(body)
          prompt = String(parsed.prompt ?? '')
          maxTokens = Number(parsed.max_tokens) || 700
        } catch {
          res.statusCode = 400
          res.end('Invalid JSON body')
          return
        }
        if (!prompt) {
          res.statusCode = 400
          res.end('Missing prompt')
          return
        }

        try {
          const anthropicRes = await fetch('https://api.anthropic.com/v1/messages', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'x-api-key': apiKey,
              'anthropic-version': '2023-06-01',
            },
            body: JSON.stringify({
              model: 'claude-sonnet-5',
              max_tokens: maxTokens,
              messages: [{ role: 'user', content: prompt }],
            }),
          })
          if (!anthropicRes.ok) {
            const errText = await anthropicRes.text()
            res.statusCode = anthropicRes.status
            res.setHeader('Content-Type', 'application/json')
            res.end(JSON.stringify({ error: errText }))
            return
          }
          const data = (await anthropicRes.json()) as { content?: { text?: string }[] }
          const content = data?.content?.[0]?.text ?? ''
          res.statusCode = 200
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify({ content }))
        } catch (err) {
          res.statusCode = 502
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify({ error: String(err) }))
        }
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react(), claudeProxyPlugin(env.ANTHROPIC_API_KEY ?? '')],
  }
})
