# University Scheduler

Vite + React frontend with a small Express API for PostgreSQL-backed demo authentication.

## Setup

1. Install dependencies:

   ```bash
   npm install
   ```

2. Create `.env` from `.env.example` and fill in the backend database URL:

   ```env
   DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE
   PORT=5000
   CLIENT_URL=http://127.0.0.1:5173
   VITE_API_URL=http://localhost:5000
   ```

   The React app only reads `VITE_API_URL`. Keep `DATABASE_URL` server-side only.

3. Run the backend:

   ```bash
   npm run server
   ```

4. Run the frontend in another terminal:

   ```bash
   npm run dev
   ```

5. Or run both together:

   ```bash
   npm run dev:full
   ```

6. Open the frontend:

   ```text
   http://127.0.0.1:5173
   ```

## Auth API

- `POST /api/auth/register`
- `POST /api/auth/login`

The backend creates the `users` table if it does not exist and stores only `password_hash`, never raw passwords.
