# PageIndex Frontend

Cognitive knowledge asset management console.

## Environment Variables

Copy `.env.example` to `.env`:

```bash
VITE_API_BASE_URL=http://localhost:22223/api/v1
```

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
- **Backend:** Default local FastAPI target is `http://localhost:22223/api/v1`.
