import express from "express";
import bcrypt from "bcryptjs";
import { pool } from "../db.js";
import { ensureSavedScheduleForUser } from "../services/scheduleService.js";

const router = express.Router();
const PASSWORD_SALT_ROUNDS = 12;

function formatUser(row) {
  return {
    id: row.id,
    email: row.email,
    username: row.username
  };
}

function normalizeEmail(email) {
  return String(email || "").trim().toLowerCase();
}

router.post("/register", async (request, response) => {
  const email = normalizeEmail(request.body.email);
  const username = String(request.body.username || "").trim();
  const password = String(request.body.password || "");

  if (!email || !username || !password) {
    return response.status(400).json({
      success: false,
      message: "Email, username, and password are required."
    });
  }

  try {
    const existingUser = await pool.query("SELECT id FROM users WHERE email = $1", [email]);

    if (existingUser.rowCount > 0) {
      return response.status(409).json({
        success: false,
        message: "An account with this email already exists."
      });
    }

    const passwordHash = await bcrypt.hash(password, PASSWORD_SALT_ROUNDS);
    const createdUser = await pool.query(
      `
        INSERT INTO users (email, username, password_hash)
        VALUES ($1, $2, $3)
        RETURNING id, email, username;
      `,
      [email, username, passwordHash]
    );
    await ensureSavedScheduleForUser(createdUser.rows[0].email);

    return response.status(201).json({
      success: true,
      message: "Account created successfully",
      user: formatUser(createdUser.rows[0])
    });
  } catch (error) {
    if (error.code === "23505") {
      return response.status(409).json({
        success: false,
        message: "An account with this email already exists."
      });
    }

    console.error("Register error:", error.message);
    return response.status(500).json({
      success: false,
      message: "Unable to create account right now."
    });
  }
});

router.post("/login", async (request, response) => {
  const email = normalizeEmail(request.body.email);
  const password = String(request.body.password || "");

  if (!email || !password) {
    return response.status(400).json({
      success: false,
      message: "Email and password are required."
    });
  }

  try {
    const userResult = await pool.query(
      "SELECT id, email, username, password_hash FROM users WHERE email = $1",
      [email]
    );

    if (userResult.rowCount === 0) {
      return response.status(401).json({
        success: false,
        message: "Email or password is incorrect."
      });
    }

    const user = userResult.rows[0];
    const passwordMatches = await bcrypt.compare(password, user.password_hash);

    if (!passwordMatches) {
      return response.status(401).json({
        success: false,
        message: "Email or password is incorrect."
      });
    }
    await ensureSavedScheduleForUser(user.email);

    return response.json({
      success: true,
      message: "Login successful",
      user: formatUser(user)
    });
  } catch (error) {
    console.error("Login error:", error.message);
    return response.status(500).json({
      success: false,
      message: "Unable to log in right now."
    });
  }
});

export default router;
