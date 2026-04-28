import { pool } from "../db.js";
import { normalizeSection } from "./courseService.js";

const DEFAULT_SAVED_SCHEDULE_NAME = "Fall 2026 Plan";

function normalizeEmail(email) {
  return String(email || "").trim().toLowerCase();
}

function normalizeCrns(crns) {
  if (!Array.isArray(crns)) {
    return null;
  }

  const normalizedCrns = [];
  const seenCrns = new Set();

  for (const crn of crns) {
    const numericCrn = Number(crn);

    if (!Number.isInteger(numericCrn) || numericCrn <= 0) {
      return null;
    }

    if (!seenCrns.has(numericCrn)) {
      seenCrns.add(numericCrn);
      normalizedCrns.push(numericCrn);
    }
  }

  return normalizedCrns;
}

async function getUserByEmail(email, client = pool) {
  const result = await client.query("SELECT email FROM users WHERE email = $1", [email]);
  return result.rows[0] || null;
}

async function getLatestScheduleRow(email, client = pool) {
  const result = await client.query(
    `
      SELECT
        generated_schedule_id,
        email,
        score,
        total_credits_of_schedule,
        created_at,
        saved_name
      FROM generated_schedules
      WHERE email = $1
      ORDER BY created_at DESC NULLS LAST, generated_schedule_id DESC
      LIMIT 1;
    `,
    [email]
  );

  return result.rows[0] || null;
}

export async function ensureSavedScheduleForUser(email, client = pool) {
  const normalizedEmail = normalizeEmail(email);

  if (!normalizedEmail) {
    return null;
  }

  const existingSchedule = await getLatestScheduleRow(normalizedEmail, client);

  if (existingSchedule) {
    return existingSchedule;
  }

  const createdSchedule = await client.query(
    `
      INSERT INTO generated_schedules (email, score, total_credits_of_schedule, created_at, saved_name)
      VALUES ($1, NULL, 0, CURRENT_TIMESTAMP, $2)
      RETURNING
        generated_schedule_id,
        email,
        score,
        total_credits_of_schedule,
        created_at,
        saved_name;
    `,
    [normalizedEmail, DEFAULT_SAVED_SCHEDULE_NAME]
  );

  return createdSchedule.rows[0] || null;
}

async function getSectionsByCrns(crns, client = pool) {
  if (crns.length === 0) {
    return [];
  }

  const result = await client.query(
    `
      SELECT
        cs.crn,
        cs.course_code,
        cs.semester,
        cs.section_number,
        cs.instructor_name,
        cs.days,
        cs.room,
        cs.start_time,
        cs.end_time,
        cs.building,
        cs.campus,
        c.title,
        c.credits,
        c.prerequisite,
        c.description
      FROM course_sections cs
      LEFT JOIN courses c ON c.course_code = cs.course_code
      WHERE cs.crn = ANY($1::int[])
      ORDER BY cs.course_code ASC, cs.section_number ASC, cs.crn ASC;
    `,
    [crns]
  );

  return result.rows;
}

function formatSchedule(row, itemRows) {
  return {
    generated_schedule_id: row.generated_schedule_id,
    email: row.email,
    saved_name: row.saved_name || DEFAULT_SAVED_SCHEDULE_NAME,
    score: row.score,
    total_credits: Number(row.total_credits_of_schedule || 0),
    created_at: row.created_at,
    items: itemRows.map(normalizeSection)
  };
}

export async function getSavedScheduleForUser(email) {
  const normalizedEmail = normalizeEmail(email);

  if (!normalizedEmail) {
    return { ok: false, status: 400, message: "Email is required." };
  }

  const user = await getUserByEmail(normalizedEmail);

  if (!user) {
    return { ok: false, status: 404, message: "User not found." };
  }

  const schedule = await ensureSavedScheduleForUser(normalizedEmail);

  const itemsResult = await pool.query(
    `
      SELECT
        cs.crn,
        cs.course_code,
        cs.semester,
        cs.section_number,
        cs.instructor_name,
        cs.days,
        cs.room,
        cs.start_time,
        cs.end_time,
        cs.building,
        cs.campus,
        c.title,
        c.credits,
        c.prerequisite,
        c.description
      FROM generated_schedule_items gsi
      JOIN course_sections cs ON cs.crn = gsi.crn
      LEFT JOIN courses c ON c.course_code = cs.course_code
      WHERE gsi.generated_schedule_id = $1
      ORDER BY cs.course_code ASC, cs.section_number ASC, cs.crn ASC;
    `,
    [schedule.generated_schedule_id]
  );

  return {
    ok: true,
    schedule: formatSchedule(schedule, itemsResult.rows)
  };
}

export async function saveScheduleForUser({ email, savedName, crns }) {
  const normalizedEmail = normalizeEmail(email);
  const normalizedCrns = normalizeCrns(crns);

  if (!normalizedEmail) {
    return { ok: false, status: 400, message: "Email is required." };
  }

  if (!normalizedCrns) {
    return { ok: false, status: 400, message: "CRNs must be an array of valid numbers." };
  }

  const client = await pool.connect();

  try {
    await client.query("BEGIN");

    const user = await getUserByEmail(normalizedEmail, client);

    if (!user) {
      await client.query("ROLLBACK");
      return { ok: false, status: 404, message: "User not found." };
    }

    const sectionRows = await getSectionsByCrns(normalizedCrns, client);
    const foundCrns = new Set(sectionRows.map((row) => Number(row.crn)));
    const missingCrns = normalizedCrns.filter((crn) => !foundCrns.has(crn));

    if (missingCrns.length > 0) {
      await client.query("ROLLBACK");
      return {
        ok: false,
        status: 400,
        message: `Could not save schedule because these CRNs were not found: ${missingCrns.join(", ")}.`
      };
    }

    const totalCredits = sectionRows.reduce((sum, row) => {
      const credits = Number(row.credits);
      return sum + (Number.isFinite(credits) ? credits : 0);
    }, 0);

    let schedule = await getLatestScheduleRow(normalizedEmail, client);
    const cleanSavedName = String(savedName || DEFAULT_SAVED_SCHEDULE_NAME).trim() || DEFAULT_SAVED_SCHEDULE_NAME;

    if (!schedule) {
      const createdSchedule = await client.query(
        `
          INSERT INTO generated_schedules (email, score, total_credits_of_schedule, created_at, saved_name)
          VALUES ($1, NULL, $2, CURRENT_TIMESTAMP, $3)
          RETURNING
            generated_schedule_id,
            email,
            score,
            total_credits_of_schedule,
            created_at,
            saved_name;
        `,
        [normalizedEmail, totalCredits, cleanSavedName]
      );
      schedule = createdSchedule.rows[0];
    } else {
      const updatedSchedule = await client.query(
        `
          UPDATE generated_schedules
          SET total_credits_of_schedule = $1,
              created_at = CURRENT_TIMESTAMP,
              saved_name = $2
          WHERE generated_schedule_id = $3
          RETURNING
            generated_schedule_id,
            email,
            score,
            total_credits_of_schedule,
            created_at,
            saved_name;
        `,
        [totalCredits, cleanSavedName, schedule.generated_schedule_id]
      );
      schedule = updatedSchedule.rows[0];
    }

    await client.query("DELETE FROM generated_schedule_items WHERE generated_schedule_id = $1", [
      schedule.generated_schedule_id
    ]);

    if (normalizedCrns.length > 0) {
      await client.query(
        `
          INSERT INTO generated_schedule_items (generated_schedule_id, crn)
          SELECT $1, UNNEST($2::int[]);
        `,
        [schedule.generated_schedule_id, normalizedCrns]
      );
    }

    await client.query("COMMIT");

    return {
      ok: true,
      schedule: formatSchedule(schedule, sectionRows)
    };
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}
