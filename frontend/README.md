# PageIndex Frontend

Cognitive knowledge asset management console.

## Environment Variables

Copy `.env.example` to `.env`:

```bash
VITE_API_BASE_URL=
```

Recommended behavior:

- leave `VITE_API_BASE_URL` empty for normal local or LAN usage
- the frontend will infer `http://<current-browser-host>:22223/api/v1`
- only set `VITE_API_BASE_URL` explicitly when you intentionally want a fixed backend target
- do not use `0.0.0.0` as a browser-facing API host

## Tech Stack

- **Framework:** React 19 + TypeScript
- **Build Tool:** Vite
- **Styling:** Tailwind CSS (Tech-style, Glassmorphism)
- **State Management:** TanStack Query (React Query)
- **Routing:** React Router v7
- **Icons:** Lucide React
- **Animations:** Framer Motion (Coming soon in more components)

## Getting Started

1. **Install Dependencies:**
   ```bash
   npm install
   ```

2. **Start Development Server:**
   ```bash
   npm run dev
   ```

3. **Build for Production:**
   ```bash
   npm run build
   ```

## Development Features

- **Auth:** Bearer token stored in localStorage.
- **Polling:** Automatic 2s polling for parse jobs.
- **Telemetry:** Real-time metrics display (latencies, token counts).
- **Responsive:** Optimized for desktop and mobile viewports.
- **Backend:** Default target follows the current browser host on port `22223`.
- **Examples:**
  - local browser on the same machine: `http://localhost:22223/api/v1`
  - LAN browser visiting `http://10.108.2.18:5173`: `http://10.108.2.18:22223/api/v1`
