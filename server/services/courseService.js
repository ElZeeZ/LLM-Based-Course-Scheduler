import { pool } from "../db.js";

const COURSE_COLORS = ["indigo", "sky", "emerald", "amber", "rose", "violet", "teal", "slate"];
const DAY_LABELS = {
  Monday: "MON",
  Tuesday: "TUE",
  Wednesday: "WED",
  Thursday: "THU",
  Friday: "FRI"
};

function valueOrNA(value) {
  if (value === null || value === undefined || String(value).trim() === "") {
    return "N/A";
  }

  return String(value).trim();
}

function compactValue(value) {
  return String(value || "").toLowerCase().replace(/\s+/g, "");
}

function getStableColor(courseCode) {
  const code = String(courseCode || "");
  const sum = Array.from(code).reduce((total, character) => total + character.charCodeAt(0), 0);
  return COURSE_COLORS[sum % COURSE_COLORS.length];
}

export function normalizeCampus(campus) {
  const normalizedCampus = String(campus || "").trim().toLowerCase();

  if (normalizedCampus === "1" || normalizedCampus === "beirut") {
    return "Beirut";
  }

  if (
    normalizedCampus === "2" ||
    normalizedCampus === "jbeil" ||
    normalizedCampus === "jbiel" ||
    normalizedCampus === "byblos"
  ) {
    return "Jbeil";
  }

  return "N/A";
}

function campusToDatabaseValue(campus) {
  const normalizedCampus = normalizeCampus(campus);

  if (normalizedCampus === "Beirut") return "1";
  if (normalizedCampus === "Jbeil") return "2";

  return "";
}

function normalizeDayToken(token) {
  const normalizedToken = String(token || "").trim().toUpperCase();

  if (normalizedToken.startsWith("MON") || normalizedToken === "M") return "Monday";
  if (normalizedToken.startsWith("TUE") || normalizedToken === "TU" || normalizedToken === "T") return "Tuesday";
  if (normalizedToken.startsWith("WED") || normalizedToken === "W") return "Wednesday";
  if (normalizedToken.startsWith("THU") || normalizedToken === "TH" || normalizedToken === "R") return "Thursday";
  if (normalizedToken.startsWith("FRI") || normalizedToken === "F") return "Friday";

  return "";
}

export function normalizeDays(days) {
  const rawDays = String(days || "").trim();

  if (!rawDays) {
    return [];
  }

  if (/[\/,;]/.test(rawDays)) {
    return Array.from(
      new Set(rawDays.split(/[\/,;]/).map(normalizeDayToken).filter(Boolean))
    );
  }

  const compactDays = rawDays.toUpperCase().replace(/[^A-Z]/g, "");

  if (["TBA", "TBD", "ARR", "ONLINE"].includes(compactDays)) {
    return [];
  }

  const normalizedDays = [];
  let index = 0;

  while (index < compactDays.length) {
    const remaining = compactDays.slice(index);

    if (remaining.startsWith("MON")) {
      normalizedDays.push("Monday");
      index += 3;
    } else if (remaining.startsWith("TUE")) {
      normalizedDays.push("Tuesday");
      index += 3;
    } else if (remaining.startsWith("WED")) {
      normalizedDays.push("Wednesday");
      index += 3;
    } else if (remaining.startsWith("THU")) {
      normalizedDays.push("Thursday");
      index += 3;
    } else if (remaining.startsWith("TH")) {
      normalizedDays.push("Thursday");
      index += 2;
    } else if (remaining.startsWith("FRI")) {
      normalizedDays.push("Friday");
      index += 3;
    } else {
      const dayName = normalizeDayToken(compactDays[index]);

      if (dayName) {
        normalizedDays.push(dayName);
      }

      index += 1;
    }
  }

  return Array.from(new Set(normalizedDays));
}

function formatDaysForDisplay(days) {
  const normalizedDays = normalizeDays(days);
  return normalizedDays.length > 0
    ? normalizedDays.map((day) => DAY_LABELS[day]).join(" / ")
    : "N/A";
}

export function formatTime(time) {
  const rawTime = String(time || "").trim();

  if (!rawTime) {
    return "N/A";
  }

  const [hoursValue, minutesValue] = rawTime.split(":");
  const hours = Number(hoursValue);
  const minutes = Number(minutesValue);

  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) {
    return "N/A";
  }

  const suffix = hours >= 12 ? "PM" : "AM";
  const displayHours = hours % 12 || 12;
  return `${displayHours}:${String(minutes).padStart(2, "0")} ${suffix}`;
}

function formatTimeValue(time) {
  const rawTime = String(time || "").trim();
  const [hoursValue, minutesValue] = rawTime.split(":");
  const hours = Number(hoursValue);
  const minutes = Number(minutesValue);

  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) {
    return "";
  }

  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

export function buildRoom(building, room) {
  const buildingValue = valueOrNA(building);
  const roomValue = valueOrNA(room);

  if (buildingValue === "N/A" && roomValue === "N/A") {
    return "N/A";
  }

  return `${buildingValue} ${roomValue}`.trim();
}

function normalizePrerequisites(prerequisite) {
  const prerequisiteValue = valueOrNA(prerequisite);

  if (prerequisiteValue === "N/A") {
    return ["N/A"];
  }

  return prerequisiteValue.split(",").map((item) => item.trim()).filter(Boolean);
}

function sectionMatchesDayFilters(sectionDays, selectedDays) {
  if (selectedDays.length === 0) {
    return true;
  }

  const selectedDaySet = new Set(selectedDays);

  if (selectedDaySet.size === 1) {
    const [selectedDay] = Array.from(selectedDaySet);
    return sectionDays.length === 1 && sectionDays[0] === selectedDay;
  }

  return sectionDays.length > 0 && sectionDays.every((day) => selectedDaySet.has(day));
}

export function normalizeSection(row) {
  const dayNames = normalizeDays(row.days);
  const startTime = formatTime(row.start_time);
  const endTime = formatTime(row.end_time);
  const courseCode = valueOrNA(row.course_code);
  const campus = normalizeCampus(row.campus);

  return {
    id: String(row.crn),
    course_id: compactValue(courseCode),
    course_code: courseCode,
    course_name: valueOrNA(row.title),
    credits: row.credits ?? "N/A",
    crn: valueOrNA(row.crn),
    section: valueOrNA(row.section_number),
    semester: valueOrNA(row.semester),
    instructor: valueOrNA(row.instructor_name),
    capacity: "N/A",
    enrolled: "N/A",
    campus,
    campuses: campus === "N/A" ? [] : [campus],
    prerequisites: normalizePrerequisites(row.prerequisite),
    description: valueOrNA(row.description),
    days: formatDaysForDisplay(row.days),
    day_names: dayNames,
    start_time: startTime,
    end_time: endTime,
    start_time_value: formatTimeValue(row.start_time),
    end_time_value: formatTimeValue(row.end_time),
    time: startTime === "N/A" || endTime === "N/A" ? "N/A" : `${startTime} - ${endTime}`,
    room: buildRoom(row.building, row.room),
    color: getStableColor(courseCode)
  };
}

export function normalizeCourseCatalogRow(row) {
  const courseCode = valueOrNA(row.course_code);
  const campuses = Array.from(
    new Set((row.campuses || []).map(normalizeCampus).filter((campus) => campus !== "N/A"))
  ).sort((firstCampus, secondCampus) => {
    const order = { Beirut: 0, Jbeil: 1 };
    return (order[firstCampus] ?? 2) - (order[secondCampus] ?? 2);
  });

  return {
    id: compactValue(courseCode),
    course_id: compactValue(courseCode),
    course_code: courseCode,
    course_name: valueOrNA(row.title),
    credits: row.credits ?? "N/A",
    campuses,
    campus: campuses.length > 0 ? campuses.join(" / ") : "N/A",
    prerequisites: normalizePrerequisites(row.prerequisite),
    description: valueOrNA(row.description),
    color: getStableColor(courseCode)
  };
}

export async function getSections({ search = "", days = [], campus = "", limit = 50 } = {}) {
  const filters = [];
  const values = [];
  const trimmedSearch = String(search || "").trim();
  const normalizedCampus = normalizeCampus(campus);
  const databaseCampus = campusToDatabaseValue(normalizedCampus);
  const selectedDays = days.flatMap(normalizeDays);
  const resultLimit = Math.min(Math.max(Number(limit) || 50, 1), 100);

  if (!trimmedSearch) {
    return [];
  }

  if (trimmedSearch) {
    values.push(`%${trimmedSearch}%`);
    const searchParam = `$${values.length}`;
    values.push(`%${compactValue(trimmedSearch)}%`);
    const compactSearchParam = `$${values.length}`;

    filters.push(`(
      CAST(cs.crn AS TEXT) ILIKE ${searchParam}
      OR cs.course_code ILIKE ${searchParam}
      OR REPLACE(LOWER(cs.course_code), ' ', '') LIKE ${compactSearchParam}
      OR c.title ILIKE ${searchParam}
      OR cs.instructor_name ILIKE ${searchParam}
    )`);
  }

  if (databaseCampus) {
    values.push(databaseCampus);
    filters.push(`cs.campus = $${values.length}`);
  }

  const whereClause = filters.length > 0 ? `WHERE ${filters.join(" AND ")}` : "";
  const candidateLimit = selectedDays.length > 0 ? 5000 : resultLimit;

  values.push(candidateLimit);
  const limitParam = `$${values.length}`;

  const result = await pool.query(
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
      ${whereClause}
      ORDER BY cs.course_code ASC, cs.section_number ASC, cs.crn ASC
      LIMIT ${limitParam};
    `,
    values
  );

  return result.rows
    .map(normalizeSection)
    .filter((section) => sectionMatchesDayFilters(section.day_names, selectedDays))
    .sort((firstSection, secondSection) => {
      if (selectedDays.length > 1 && firstSection.day_names.length !== secondSection.day_names.length) {
        return secondSection.day_names.length - firstSection.day_names.length;
      }

      return (
        firstSection.course_code.localeCompare(secondSection.course_code) ||
        Number(firstSection.section) - Number(secondSection.section) ||
        Number(firstSection.crn) - Number(secondSection.crn)
      );
    })
    .slice(0, resultLimit);
}

export async function getSectionsForCourses({
  courses = [],
  courseCodes = [],
  searchTerms = [],
  campus = "",
  limitPerCourse = 20
} = {}) {
  const normalizedSelections = normalizeCourseSelections(courses, courseCodes, searchTerms, campus);
  const selectedSections = [];
  const selectedCrns = new Set();
  const perCourseLimit = Math.min(Math.max(Number(limitPerCourse) || 20, 1), 50);

  for (const selection of normalizedSelections) {
    const sections = await getSections({
      search: selection.course_code,
      campus: selection.campus,
      limit: perCourseLimit
    });
    const requestedCode = compactValue(selection.course_code);
    const shouldMatchExactCourseCode = /^[a-z]{2,5}\d{3}[a-z]?$/i.test(requestedCode);

    sections
      .filter((section) => !shouldMatchExactCourseCode || compactValue(section.course_code) === requestedCode)
      .forEach((section) => {
        if (!selectedCrns.has(section.crn)) {
          selectedCrns.add(section.crn);
          selectedSections.push(section);
        }
      });
  }

  return selectedSections;
}

export async function getExactSectionsForCourses({
  courses = [],
  courseCodes = [],
  crns = [],
  campus = "",
  limitPerCourse = 20
} = {}) {
  const exactCourseCodes = normalizeExactCourseCodes(courses, courseCodes);
  const exactCrns = normalizeCrns(crns);
  const databaseCampus = campusToDatabaseValue(campus);
  const perCourseLimit = Math.min(Math.max(Number(limitPerCourse) || 20, 1), 50);
  const resultLimit = Math.min(Math.max((exactCourseCodes.length + exactCrns.length || 1) * perCourseLimit, 1), 500);

  if (exactCourseCodes.length === 0 && exactCrns.length === 0) {
    return [];
  }

  const filters = [];
  const values = [];

  if (exactCourseCodes.length > 0) {
    values.push(exactCourseCodes);
    filters.push("REPLACE(LOWER(cs.course_code), ' ', '') = ANY($" + values.length + "::text[])");
  }

  if (exactCrns.length > 0) {
    values.push(exactCrns);
    filters.push("CAST(cs.crn AS TEXT) = ANY($" + values.length + "::text[])");
  }

  const whereParts = [`(${filters.join(" OR ")})`];
  if (databaseCampus) {
    values.push(databaseCampus);
    whereParts.push(`cs.campus = $${values.length}`);
  }

  values.push(resultLimit);
  const limitParam = `$${values.length}`;

  const result = await pool.query(
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
      WHERE ${whereParts.join(" AND ")}
      ORDER BY cs.course_code ASC, cs.section_number ASC, cs.crn ASC
      LIMIT ${limitParam};
    `,
    values
  );

  return result.rows.map(normalizeSection);
}

function normalizeCourseSelections(courses, courseCodes, searchTerms, campus) {
  const selections = [];
  const seen = new Set();
  const globalCampus = normalizeCampus(campus);

  function addSelection(courseCode, preferredCampus = "") {
    const code = valueOrNA(courseCode);
    if (code === "N/A") {
      return;
    }

    const selectedCampus = normalizeCampus(preferredCampus || globalCampus);
    const campusValue = selectedCampus === "N/A" ? "" : selectedCampus;
    const key = `${compactValue(code)}:${compactValue(campusValue)}`;

    if (seen.has(key)) {
      return;
    }

    seen.add(key);
    selections.push({
      course_code: code,
      campus: campusValue
    });
  }

  (Array.isArray(courses) ? courses : []).forEach((course) => {
    addSelection(course.course_code || course.code, course.campus);
  });

  (Array.isArray(courseCodes) ? courseCodes : []).forEach((courseCode) => {
    addSelection(courseCode, globalCampus);
  });

  (Array.isArray(searchTerms) ? searchTerms : []).forEach((searchTerm) => {
    addSelection(searchTerm, globalCampus);
  });

  return selections;
}

function normalizeExactCourseCodes(courses, courseCodes) {
  const codes = [];
  const seen = new Set();

  function addCode(value) {
    const compactCode = compactValue(value);
    if (!/^[a-z]{2,5}\d{3}[a-z]?$/.test(compactCode) || seen.has(compactCode)) {
      return;
    }
    seen.add(compactCode);
    codes.push(compactCode);
  }

  (Array.isArray(courses) ? courses : []).forEach((course) => {
    addCode(course.course_code || course.code || course.course_id);
  });

  (Array.isArray(courseCodes) ? courseCodes : []).forEach(addCode);

  return codes;
}

function normalizeCrns(crns) {
  const normalizedCrns = [];
  const seen = new Set();

  (Array.isArray(crns) ? crns : []).forEach((crn) => {
    const value = String(crn || "").trim();
    if (!/^\d{4,6}$/.test(value) || seen.has(value)) {
      return;
    }
    seen.add(value);
    normalizedCrns.push(value);
  });

  return normalizedCrns;
}

export async function getCourseCatalog({ search = "", campus = "", limit = 100 } = {}) {
  const filters = [];
  const values = [];
  const trimmedSearch = String(search || "").trim();
  const databaseCampus = campusToDatabaseValue(campus);
  const resultLimit = Math.min(Math.max(Number(limit) || 100, 1), 200);

  if (!trimmedSearch) {
    return [];
  }

  if (trimmedSearch) {
    values.push(`%${trimmedSearch}%`);
    const searchParam = `$${values.length}`;
    values.push(`%${compactValue(trimmedSearch)}%`);
    const compactSearchParam = `$${values.length}`;

    filters.push(`(
      cs.course_code ILIKE ${searchParam}
      OR REPLACE(LOWER(cs.course_code), ' ', '') LIKE ${compactSearchParam}
      OR c.title ILIKE ${searchParam}
    )`);
  }

  if (databaseCampus) {
    values.push(databaseCampus);
    filters.push(`cs.campus = $${values.length}`);
  }

  const whereClause = filters.length > 0 ? `WHERE ${filters.join(" AND ")}` : "";

  values.push(resultLimit);
  const limitParam = `$${values.length}`;

  const result = await pool.query(
    `
      SELECT
        cs.course_code,
        c.title,
        c.credits,
        c.prerequisite,
        c.description,
        ARRAY_AGG(DISTINCT cs.campus) AS campuses
      FROM course_sections cs
      LEFT JOIN courses c ON c.course_code = cs.course_code
      ${whereClause}
      GROUP BY cs.course_code, c.title, c.credits, c.prerequisite, c.description
      ORDER BY cs.course_code ASC
      LIMIT ${limitParam};
    `,
    values
  );

  return result.rows.map(normalizeCourseCatalogRow);
}

export async function getCourseHealth() {
  const sections = await pool.query("SELECT COUNT(*)::int AS count FROM course_sections;");
  const courses = await pool.query("SELECT COUNT(*)::int AS count FROM courses;");

  return {
    sections: sections.rows[0]?.count || 0,
    courses: courses.rows[0]?.count || 0
  };
}
