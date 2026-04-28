import "dotenv/config";
import pg from "pg";
import bcrypt from "bcryptjs";

const { Pool } = pg;
const PASSWORD_SALT_ROUNDS = 12;

function getSSLConfig() {
  const databaseUrl = process.env.DATABASE_URL || "";

  if (process.env.PGSSLMODE === "disable") {
    return false;
  }

  if (
    process.env.PGSSLMODE === "require" ||
    databaseUrl.includes("render.com") ||
    databaseUrl.includes("sslmode=require")
  ) {
    return { rejectUnauthorized: false };
  }

  return false;
}

export const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: getSSLConfig()
});

pool.on("error", (error) => {
  console.error("Unexpected PostgreSQL client error:", error.message);
});

export async function initializeDatabase() {
  if (!process.env.DATABASE_URL) {
    throw new Error("DATABASE_URL is required. Add it to .env before starting the server.");
  }

  await pool.query(`
    CREATE TABLE IF NOT EXISTS users (
      id SERIAL PRIMARY KEY,
      email TEXT UNIQUE NOT NULL,
      username TEXT NOT NULL,
      password_hash TEXT NOT NULL,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
  `);

  await pool.query("ALTER TABLE users ADD COLUMN IF NOT EXISTS id INTEGER;");
  await pool.query("CREATE SEQUENCE IF NOT EXISTS users_id_seq OWNED BY users.id;");
  await pool.query("ALTER TABLE users ALTER COLUMN id SET DEFAULT nextval('users_id_seq');");
  await pool.query("UPDATE users SET id = nextval('users_id_seq') WHERE id IS NULL;");
  await pool.query(`
    SELECT setval(
      'users_id_seq',
      COALESCE((SELECT MAX(id) FROM users), 1),
      (SELECT COUNT(*) FROM users) > 0
    );
  `);
  await pool.query("CREATE UNIQUE INDEX IF NOT EXISTS users_id_unique_idx ON users (id);");
  await pool.query("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT;");
  await pool.query("ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;");
  await pool.query("CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique_idx ON users (email);");

  await pool.query(`
    CREATE TABLE IF NOT EXISTS generated_schedules (
      generated_schedule_id SERIAL PRIMARY KEY,
      email TEXT NOT NULL,
      score NUMERIC,
      total_credits_of_schedule NUMERIC DEFAULT 0,
      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      saved_name TEXT
    );
  `);

  await pool.query(`
    CREATE TABLE IF NOT EXISTS generated_schedule_items (
      generated_schedule_id INTEGER NOT NULL,
      crn INTEGER NOT NULL,
      PRIMARY KEY (generated_schedule_id, crn)
    );
  `);

  await pool.query("ALTER TABLE generated_schedules ADD COLUMN IF NOT EXISTS score NUMERIC;");
  await pool.query("ALTER TABLE generated_schedules ADD COLUMN IF NOT EXISTS total_credits_of_schedule NUMERIC DEFAULT 0;");
  await pool.query("ALTER TABLE generated_schedules ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;");
  await pool.query("ALTER TABLE generated_schedules ADD COLUMN IF NOT EXISTS saved_name TEXT;");
  await pool.query("CREATE INDEX IF NOT EXISTS generated_schedules_email_idx ON generated_schedules (email);");
  await pool.query("CREATE INDEX IF NOT EXISTS generated_schedule_items_schedule_idx ON generated_schedule_items (generated_schedule_id);");
  await pool.query("CREATE INDEX IF NOT EXISTS generated_schedule_items_crn_idx ON generated_schedule_items (crn);");

  const legacyPasswordColumn = await pool.query(`
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'users'
      AND column_name = 'password';
  `);

  if (legacyPasswordColumn.rowCount > 0) {
    const legacyUsers = await pool.query(`
      SELECT email, password
      FROM users
      WHERE password_hash IS NULL
        AND password IS NOT NULL
        AND password <> '';
    `);

    for (const user of legacyUsers.rows) {
      const passwordHash = await bcrypt.hash(user.password, PASSWORD_SALT_ROUNDS);
      await pool.query(
        "UPDATE users SET password_hash = $1, password = NULL WHERE email = $2",
        [passwordHash, user.email]
      );
    }
  }
}
