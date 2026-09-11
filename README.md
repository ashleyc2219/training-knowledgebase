# Training Knowledge Base

A self-improving Training Knowledge Base for IT/Copilot enablement teams — turns recurring support
tickets into tutorials, turns user feedback into refinements, and turns product release notes into
tutorial updates, with every change backed by visible evidence.

Full spec: see the design doc shared in the project chat (not checked into this repo). Summary of the
core loop:

```
Ticket → Knowledge Gap → Tutorial v1 → Feedback → Refine → Tutorial v2 → Release Note → Update → Tutorial v3
```

## Current state

**Frontend only, fully working, no backend yet.** Everything — the "database," the ticket-clustering
logic, the release-note rename detection, the tutorial generation — currently runs as a simulated
agent inside the browser (see [`frontend/src/api/agentEngine.ts`](frontend/src/api/agentEngine.ts)).
This was intentional: it lets the full product loop be demoed end-to-end today, without waiting on a
real backend, and every function in [`frontend/src/api/client.ts`](frontend/src/api/client.ts) is
already shaped like the real REST API (`GET /api/tutorials`, `POST /api/events/ticket`, etc.) so
swapping in real `fetch()` calls later shouldn't require touching any component.

**Not real:** there's no database (state lives in an in-memory JS object, reset on every page
reload), no Cognee/HydraDB/Rote/Hotdata/RocketRide integration, and ticket clustering is
keyword-overlap, not semantic search.

**Is real:** tutorial generation and feedback-driven refinement can call the actual Claude API for
real content — see "Optional: real Claude generation" below. Falls back to hand-curated / templated
content if no key is configured, so the demo never breaks either way.

## Quick start

```bash
cd frontend
npm install
npm run dev
```

Opens at `http://localhost:5173`. Two pages: **Tutorial Hub** (`/tutorials`) and **AI Improvement
Console** (`/improvement`) — the Console is where you simulate incoming tickets and release notes,
and see knowledge gaps / tutorial health / agent actions react live.

## Optional: real Claude generation

```bash
cd frontend
cp .env.example .env
# edit .env, set ANTHROPIC_API_KEY=sk-ant-...
```

Restart `npm run dev` after adding the key. This is proxied through a small Vite dev-server plugin
([`frontend/vite.config.ts`](frontend/vite.config.ts)) so the key stays server-side and is never sent
to the browser — do **not** call the Anthropic API directly from frontend code.

## Repo structure

```
frontend/
├── src/
│   ├── types.ts              data model (mirrors the design doc's entities)
│   ├── api/
│   │   ├── client.ts          mock API — shaped like the real REST endpoints
│   │   ├── store.ts           in-memory "database"
│   │   ├── agentEngine.ts     simulated agent: ticket clustering, tutorial
│   │   │                      generation, refine/update logic
│   │   ├── llm.ts             client for the Claude proxy
│   │   ├── mockData.ts        seed data (the "Meeting Preparation" demo scenario)
│   │   └── sampleTickets.ts   sample tickets for the ticket-simulator's dice button
│   ├── components/            TutorialCard, TutorialViewer, FeedbackForm,
│   │                          TutorialHealth, KnowledgeGap, AgentActivity,
│   │                          VersionDiff, TicketPanel, ReleasePanel, …
│   └── pages/
│       ├── tutorials/         Tutorial Hub + tutorial detail page
│       └── improvement/       AI Improvement Console
└── vite.config.ts             includes the dev-only Claude proxy
```

## For whoever builds the real backend

Replace the function bodies in `frontend/src/api/client.ts` with real `fetch()` calls — the
signatures and return shapes already match what's described as the API surface in the design doc
(`GET /api/tutorials`, `POST /api/tutorials/:id/feedback`, `POST /api/events/ticket`, etc.). Nothing
else in the frontend should need to change.
