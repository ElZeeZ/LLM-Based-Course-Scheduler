import "dotenv/config";
import express from "express";
import cors from "cors";
import authRoutes from "./routes/auth.js";
import coursesRoutes from "./routes/courses.js";
import schedulesRoutes from "./routes/schedules.js";
import { initializeDatabase } from "./db.js";

const app = express();
const port = Number(process.env.PORT) || 5000;

function getAllowedOrigins() {
  return new Set(
    (process.env.CLIENT_URL || "http://127.0.0.1:5173")
      .split(",")
      .map((origin) => origin.trim())
      .filter(Boolean)
  );
}

function isLocalDevOrigin(origin) {
  if (process.env.NODE_ENV === "production") {
    return false;
  }

  return /^http:\/\/(localhost|127\.0\.0\.1):\d+$/.test(origin);
}

const allowedOrigins = getAllowedOrigins();

app.use(
  cors({
    origin(origin, callback) {
      if (!origin || allowedOrigins.has(origin) || isLocalDevOrigin(origin)) {
        callback(null, true);
        return;
      }

      callback(new Error("Not allowed by CORS"));
    }
  })
);
app.use(express.json({ limit: "1mb" }));

app.get("/api/health", (_request, response) => {
  response.json({ success: true, message: "Scheduler API is running" });
});

app.use("/api/auth", authRoutes);
app.use("/api/courses", coursesRoutes);
app.use("/api/schedules", schedulesRoutes);

app.use((_request, response) => {
  response.status(404).json({ success: false, message: "Route not found." });
});

app.use((error, _request, response, _next) => {
  console.error("Server error:", error.message);
  response.status(500).json({ success: false, message: "Server error." });
});

async function startServer() {
  await initializeDatabase();

  app.listen(port, () => {
    console.log(`Scheduler API listening on http://localhost:${port}`);
  });
}

startServer().catch((error) => {
  console.error("Failed to start Scheduler API:", error.message);
  process.exit(1);
});

export default app;
