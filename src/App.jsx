import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  BadgeCheck,
  Bot,
  BookOpen,
  Building2,
  CalendarDays,
  Check,
  CheckCircle2,
  Clock3,
  GraduationCap,
  KeyRound,
  LogOut,
  Mail,
  MapPin,
  MessageCircle,
  Plus,
  Search,
  Send,
  Sparkles,
  Trash2,
  User,
  X
} from "lucide-react";

/* =========================
   Constants And Utilities
========================= */

const WEEK_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"];
const DAY_SHORT_LABELS = {
  Monday: "MON",
  Tuesday: "TUE",
  Wednesday: "WED",
  Thursday: "THU",
  Friday: "FRI"
};

const DAY_FILTERS = [
  { label: "Mon", value: "Monday" },
  { label: "Tue", value: "Tuesday" },
  { label: "Wed", value: "Wednesday" },
  { label: "Thu", value: "Thursday" },
  { label: "Fri", value: "Friday" }
];

const SCHEDULE_START_HOUR = 8;
const SCHEDULE_END_HOUR = 18;
const SCHEDULE_START_MINUTES = SCHEDULE_START_HOUR * 60;
const SCHEDULE_END_MINUTES = SCHEDULE_END_HOUR * 60;
const SCHEDULE_TOTAL_MINUTES = SCHEDULE_END_MINUTES - SCHEDULE_START_MINUTES;

const COURSE_COLORS = {
  indigo: { accent: "#4f46e5", soft: "#eef2ff", border: "#c7d2fe", text: "#312e81" },
  sky: { accent: "#0284c7", soft: "#e0f2fe", border: "#bae6fd", text: "#075985" },
  emerald: { accent: "#059669", soft: "#d1fae5", border: "#a7f3d0", text: "#065f46" },
  amber: { accent: "#d97706", soft: "#fef3c7", border: "#fde68a", text: "#92400e" },
  rose: { accent: "#e11d48", soft: "#ffe4e6", border: "#fecdd3", text: "#9f1239" },
  violet: { accent: "#7c3aed", soft: "#ede9fe", border: "#ddd6fe", text: "#5b21b6" },
  teal: { accent: "#0f766e", soft: "#ccfbf1", border: "#99f6e4", text: "#115e59" },
  slate: { accent: "#475569", soft: "#f1f5f9", border: "#cbd5e1", text: "#334155" }
};

const API_BASE_URL = (import.meta.env.VITE_API_URL || "http://localhost:5000").replace(/\/$/, "");
const LLM_API_BASE_URL = (import.meta.env.VITE_LLM_API_URL || "http://localhost:8000").replace(/\/$/, "");

async function getApiData(path, queryParams = {}) {
  const url = new URL(`${API_BASE_URL}${path}`);

  Object.entries(queryParams).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      url.searchParams.set(key, value);
    }
  });

  const response = await fetch(url);
  const data = await response.json().catch(() => ({}));

  if (!response.ok || data.success === false) {
    throw new Error(data.message || "Unable to load data.");
  }

  return data;
}

async function postAuthRequest(path, payload) {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
    const data = await response.json().catch(() => ({}));

    if (!response.ok || data.success === false) {
      return {
        success: false,
        message: data.message || "Authentication request failed."
      };
    }

    return data;
  } catch {
    return {
      success: false,
      message: "Could not reach the authentication server."
    };
  }
}

async function postApiData(path, payload) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
  const data = await response.json().catch(() => ({}));

  if (!response.ok || data.success === false) {
    throw new Error(data.message || "Unable to save data.");
  }

  return data;
}

async function postLlmRequest(path, payload) {
  const response = await fetch(`${LLM_API_BASE_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(data.detail || data.message || "Unable to reach the AI scheduler.");
  }

  return data;
}

function shouldUseScheduleEndpoint(message, planningCourses) {
  const text = String(message || "").toLowerCase();
  const hasScheduleIntent = /\b(schedule|timetable|plan|semester|section|sections|crn|conflict|optimi[sz]e)\b/.test(text);
  const hasScheduleMutation = /\b(remove|drop|delete|take out|exclude|avoid|without|not with|do not want|don't want|dont want)\b/.test(text);
  const hasDayPreference = /\b(mwf|m\/w\/f|tr|t\/r|tuesday\s+(and\s+)?thursday|monday\s+wednesday\s+friday)\b/.test(text);
  const hasInstructorPreference = /\b(instructor|professor|prof|dr\.?)\b/.test(text);
  const hasPlanningContext = planningCourses.length > 0;

  return hasScheduleIntent || hasScheduleMutation || hasDayPreference || hasInstructorPreference || hasPlanningContext;
}

function shouldUseCourseSearchEndpoint(message, planningCourses) {
  const text = String(message || "").toLowerCase();
  const hasDiscoveryIntent = /\b(find|search|show|list|what|which|get|give me|recommend)\b/.test(text);
  const hasSemanticCue = /\b(relevant|related|similar|description|descriptions|about|involve|involves|based on|topic|topics|courses?)\b/.test(text);
  const hasScheduleIntent = /\b(schedule|timetable|plan|semester|section|sections|crn|conflict|optimi[sz]e)\b/.test(text);
  const hasScheduleMutation = /\b(remove|drop|delete|take out|exclude|avoid|without|not with|do not want|don't want|dont want)\b/.test(text);
  const hasDayPreference = /\b(mwf|m\/w\/f|tr|t\/r|tuesday\s+(and\s+)?thursday|monday\s+wednesday\s+friday)\b/.test(text);

  return (
    (hasDiscoveryIntent || hasSemanticCue) &&
    !hasScheduleIntent &&
    !hasScheduleMutation &&
    !hasDayPreference
  );
}

function parseTimeParts(time) {
  const rawTime = String(time || "").trim();
  const match = rawTime.match(/^(\d{1,2}):(\d{2})(?::\d{2})?\s*(AM|PM)?$/i);

  if (!match) {
    return null;
  }

  let hours = Number(match[1]);
  const minutes = Number(match[2]);
  const meridiem = match[3]?.toUpperCase();

  if (!Number.isFinite(hours) || !Number.isFinite(minutes)) {
    return null;
  }

  if (meridiem === "PM" && hours !== 12) {
    hours += 12;
  }

  if (meridiem === "AM" && hours === 12) {
    hours = 0;
  }

  return { hours, minutes };
}

function timeToMinutes(time) {
  const parsedTime = parseTimeParts(time);
  return parsedTime ? parsedTime.hours * 60 + parsedTime.minutes : Number.NaN;
}

function formatTime(time) {
  const parsedTime = parseTimeParts(time);

  if (!parsedTime) {
    return "N/A";
  }

  const { hours, minutes } = parsedTime;
  const suffix = hours >= 12 ? "PM" : "AM";
  const displayHours = hours % 12 || 12;
  return `${displayHours}:${String(minutes).padStart(2, "0")} ${suffix}`;
}

function formatTimeRange(course) {
  if (course.time && course.time !== "N/A") {
    return course.time;
  }

  return `${formatTime(course.start_time)} - ${formatTime(course.end_time)}`;
}

function formatDays(days) {
  const normalizedDays = getNormalizedSectionDays(days);
  return normalizedDays.length > 0 ? normalizedDays.map((day) => DAY_SHORT_LABELS[day]).join(" / ") : "N/A";
}

function normalizeSearchValue(value) {
  return String(value || "").toLowerCase().replace(/\s+/g, "");
}

function normalizeDayName(day) {
  const normalizedDay = String(day).trim().toLowerCase();

  if (normalizedDay.startsWith("mon")) return "Monday";
  if (normalizedDay.startsWith("tue")) return "Tuesday";
  if (normalizedDay.startsWith("wed")) return "Wednesday";
  if (normalizedDay.startsWith("thu")) return "Thursday";
  if (normalizedDay.startsWith("fri")) return "Friday";

  return "";
}

function getNormalizedSectionDays(days) {
  if (!days) {
    return [];
  }

  const dayParts = Array.isArray(days)
    ? days
    : String(days).split(/[\/,]/).map((day) => day.trim());

  return Array.from(new Set(dayParts.map(normalizeDayName).filter(Boolean)));
}

function sectionMatchesDayFilters(section, selectedDays) {
  if (selectedDays.length === 0) {
    return true;
  }

  const sectionDays = getNormalizedSectionDays(section.days);
  const selectedDaySet = new Set(selectedDays.map(normalizeDayName));

  if (selectedDaySet.size === 1) {
    const [selectedDay] = Array.from(selectedDaySet);
    return sectionDays.length === 1 && sectionDays[0] === selectedDay;
  }

  return sectionDays.length > 0 && sectionDays.every((day) => selectedDaySet.has(day));
}

function safeText(value, fallback = "N/A") {
  if (value === null || value === undefined || String(value).trim() === "") {
    return fallback;
  }

  return String(value).trim();
}

function normalizeCredits(value) {
  const numericCredits = Number(value);
  return Number.isFinite(numericCredits) ? numericCredits : 0;
}

function normalizePrerequisites(value) {
  if (Array.isArray(value)) {
    return value.length > 0 ? value.map((item) => safeText(item)).filter(Boolean) : ["N/A"];
  }

  const prerequisiteText = safeText(value);
  return prerequisiteText === "N/A"
    ? ["N/A"]
    : prerequisiteText.split(",").map((item) => item.trim()).filter(Boolean);
}

function normalizeApiSection(section) {
  const courseCode = safeText(section.course_code);
  const dayNames = Array.isArray(section.day_names)
    ? section.day_names
    : getNormalizedSectionDays(section.days);
  const startTime = safeText(section.start_time_value || section.start_time, "");
  const endTime = safeText(section.end_time_value || section.end_time, "");
  const displayStartTime = safeText(section.start_time);
  const displayEndTime = safeText(section.end_time);
  const time = section.time && section.time !== "N/A"
    ? section.time
    : `${formatTime(displayStartTime || startTime)} - ${formatTime(displayEndTime || endTime)}`;

  return {
    id: safeText(section.id || section.crn || `${courseCode}-${section.section}`),
    course_id: safeText(section.course_id || normalizeSearchValue(courseCode)),
    course_code: courseCode,
    course_name: safeText(section.course_name),
    credits: normalizeCredits(section.credits),
    creditsLabel: Number.isFinite(Number(section.credits)) ? `${Number(section.credits)} credits` : "N/A credits",
    crn: safeText(section.crn),
    section: safeText(section.section),
    semester: safeText(section.semester),
    instructor: safeText(section.instructor),
    capacity: safeText(section.capacity),
    enrolled: safeText(section.enrolled),
    campus: safeText(section.campus),
    campuses: Array.isArray(section.campuses) ? section.campuses : [safeText(section.campus)],
    prerequisites: normalizePrerequisites(section.prerequisites),
    description: safeText(section.description),
    days: dayNames,
    start_time: startTime || displayStartTime,
    end_time: endTime || displayEndTime,
    time,
    room: safeText(section.room),
    color: section.color || "indigo"
  };
}

function normalizeApiCatalogCourse(course) {
  const courseCode = safeText(course.course_code);
  const campuses = Array.isArray(course.campuses)
    ? course.campuses.filter((campus) => safeText(campus) !== "N/A")
    : [];

  return {
    id: safeText(course.id || course.course_id || normalizeSearchValue(courseCode)),
    course_id: safeText(course.course_id || course.id || normalizeSearchValue(courseCode)),
    course_code: courseCode,
    course_name: safeText(course.course_name),
    credits: normalizeCredits(course.credits),
    campuses,
    campus: campuses.length > 0 ? campuses.join(" / ") : "N/A",
    prerequisites: normalizePrerequisites(course.prerequisites),
    description: safeText(course.description),
    color: course.color || "indigo"
  };
}

function formatCredits(course) {
  return course.creditsLabel || `${course.credits} credits`;
}

function getCoursePalette(colorName) {
  return COURSE_COLORS[colorName] || COURSE_COLORS.indigo;
}

function hasTimeOverlap(firstCourse, secondCourse) {
  const firstStart = timeToMinutes(firstCourse.start_time);
  const firstEnd = timeToMinutes(firstCourse.end_time);
  const secondStart = timeToMinutes(secondCourse.start_time);
  const secondEnd = timeToMinutes(secondCourse.end_time);

  if (![firstStart, firstEnd, secondStart, secondEnd].every(Number.isFinite)) {
    return false;
  }

  return firstStart < secondEnd && secondStart < firstEnd;
}

function detectScheduleConflicts(courses) {
  const pairs = [];
  const conflictCourseIds = new Set();

  for (let firstIndex = 0; firstIndex < courses.length; firstIndex += 1) {
    for (let secondIndex = firstIndex + 1; secondIndex < courses.length; secondIndex += 1) {
      const firstCourse = courses[firstIndex];
      const secondCourse = courses[secondIndex];
      const commonDays = firstCourse.days.filter((day) => secondCourse.days.includes(day));

      if (commonDays.length > 0 && hasTimeOverlap(firstCourse, secondCourse)) {
        pairs.push({
          id: `${firstCourse.id}-${secondCourse.id}`,
          courses: [firstCourse, secondCourse],
          days: commonDays
        });
        conflictCourseIds.add(firstCourse.id);
        conflictCourseIds.add(secondCourse.id);
      }
    }
  }

  return {
    pairs,
    conflictCourseIds
  };
}

function getWeeklyHours(courses) {
  const totalMinutes = courses.reduce((sum, course) => {
    const duration = timeToMinutes(course.end_time) - timeToMinutes(course.start_time);
    if (!Number.isFinite(duration)) {
      return sum;
    }

    return sum + duration * course.days.length;
  }, 0);

  return (totalMinutes / 60).toFixed(1);
}

function getTimetableInstances(courses, conflictCourseIds) {
  const instancesByDay = WEEK_DAYS.reduce((accumulator, day) => {
    accumulator[day] = [];
    return accumulator;
  }, {});

  courses.forEach((course) => {
    const startMinutes = timeToMinutes(course.start_time);
    const endMinutes = timeToMinutes(course.end_time);

    if (!Number.isFinite(startMinutes) || !Number.isFinite(endMinutes)) {
      return;
    }

    course.days.forEach((day) => {
      if (instancesByDay[day]) {
        instancesByDay[day].push({
          ...course,
          instanceId: `${course.id}-${day}`,
          day,
          dayIndex: WEEK_DAYS.indexOf(day),
          startMinutes,
          endMinutes,
          isConflict: conflictCourseIds.has(course.id)
        });
      }
    });
  });

  return WEEK_DAYS.flatMap((day) => {
    const sortedInstances = [...instancesByDay[day]].sort((first, second) => {
      return first.startMinutes - second.startMinutes || first.endMinutes - second.endMinutes;
    });

    const clusters = [];
    let currentCluster = [];
    let currentClusterEnd = 0;

    sortedInstances.forEach((instance) => {
      if (currentCluster.length === 0 || instance.startMinutes < currentClusterEnd) {
        currentCluster.push(instance);
        currentClusterEnd = Math.max(currentClusterEnd, instance.endMinutes);
      } else {
        clusters.push(currentCluster);
        currentCluster = [instance];
        currentClusterEnd = instance.endMinutes;
      }
    });

    if (currentCluster.length > 0) {
      clusters.push(currentCluster);
    }

    return clusters.flatMap((cluster) => {
      const lanes = [];

      const withLanes = cluster.map((instance) => {
        let laneIndex = lanes.findIndex((laneEnd) => laneEnd <= instance.startMinutes);

        if (laneIndex === -1) {
          laneIndex = lanes.length;
          lanes.push(instance.endMinutes);
        } else {
          lanes[laneIndex] = instance.endMinutes;
        }

        return {
          ...instance,
          laneIndex
        };
      });

      const laneCount = Math.max(lanes.length, 1);

      return withLanes.map((instance) => ({
        ...instance,
        laneCount
      }));
    });
  });
}

/* =========================
   Mock Course Data
========================= */

const mockCoursesTable = [
  {
    course_id: "COE522",
    course_code: "COE 522",
    title: "Machine Learning",
    credits: 3,
    prerequisite: "COE 321, MTH 304",
    description: "Supervised learning, model evaluation, feature engineering, and applied AI workflows."
  },
  {
    course_id: "COE424",
    course_code: "COE 424",
    title: "Digital Systems",
    credits: 3,
    prerequisite: "COE 224",
    description: "Digital logic, synchronous design, HDL modeling, and programmable hardware basics."
  },
  {
    course_id: "COE321",
    course_code: "COE 321",
    title: "Database Systems",
    credits: 3,
    prerequisite: "COE 241",
    description: "Relational modeling, SQL, transactions, indexing, and database application design."
  },
  {
    course_id: "COE444",
    course_code: "COE 444",
    title: "Computer Networks",
    credits: 3,
    prerequisite: "COE 343",
    description: "Network layers, routing, transport protocols, congestion control, and network security."
  },
  {
    course_id: "COE491",
    course_code: "COE 491",
    title: "Senior Project",
    credits: 3,
    prerequisite: "Senior standing",
    description: "Capstone design project with documentation, implementation, testing, and presentation."
  },
  {
    course_id: "MTH304",
    course_code: "MTH 304",
    title: "Probability and Statistics",
    credits: 3,
    prerequisite: "MTH 201",
    description: "Probability models, random variables, distributions, estimation, and hypothesis testing."
  },
  {
    course_id: "COE430",
    course_code: "COE 430",
    title: "Software Engineering",
    credits: 3,
    prerequisite: "COE 321",
    description: "Requirements, architecture, testing, team workflows, and maintainable software delivery."
  },
  {
    course_id: "COE450",
    course_code: "COE 450",
    title: "Operating Systems",
    credits: 3,
    prerequisite: "COE 341",
    description: "Processes, scheduling, memory management, filesystems, synchronization, and concurrency."
  }
];

const mockCourseSectionsTable = [
  {
    id: "section-coe522-01",
    CRN: 52201,
    course_code: "COE522",
    semester: "Fall 2026",
    section_number: "01",
    instructor_name: "Dr. Lina Haddad",
    capacity: 32,
    actual_enrolled: 27,
    remaining_seats: 5,
    campus: "Beirut",
    days: ["Monday", "Wednesday"],
    room: "Engineering Hall 204",
    start_time: "10:30",
    end_time: "11:45",
    color: "indigo"
  },
  {
    id: "section-coe522-02",
    CRN: 52202,
    course_code: "COE522",
    semester: "Fall 2026",
    section_number: "02",
    instructor_name: "Dr. Rami Khoury",
    capacity: 34,
    actual_enrolled: 21,
    remaining_seats: 13,
    campus: "Beirut",
    days: ["Tuesday", "Thursday"],
    room: "AI Lab 306",
    start_time: "14:00",
    end_time: "15:15",
    color: "indigo"
  },
  {
    id: "section-coe522-03",
    CRN: 52203,
    course_code: "COE522",
    semester: "Fall 2026",
    section_number: "03",
    instructor_name: "Dr. Yasmina Raad",
    capacity: 28,
    actual_enrolled: 18,
    remaining_seats: 10,
    campus: "Jbeil",
    days: ["Monday", "Wednesday"],
    room: "Jbeil Tech Hub 118",
    start_time: "15:00",
    end_time: "16:15",
    color: "indigo"
  },
  {
    id: "section-coe424-01",
    CRN: 42418,
    course_code: "COE424",
    semester: "Fall 2026",
    section_number: "01",
    instructor_name: "Dr. Omar Hamdan",
    capacity: 30,
    actual_enrolled: 30,
    remaining_seats: 0,
    campus: "Jbeil",
    days: ["Monday", "Wednesday"],
    room: "Systems Lab 112",
    start_time: "10:00",
    end_time: "11:15",
    color: "sky"
  },
  {
    id: "section-coe321-01",
    CRN: 32107,
    course_code: "COE321",
    semester: "Fall 2026",
    section_number: "02",
    instructor_name: "Dr. Maya Nasser",
    capacity: 38,
    actual_enrolled: 31,
    remaining_seats: 7,
    campus: "Beirut",
    days: ["Tuesday", "Thursday"],
    room: "Technology Center 308",
    start_time: "12:00",
    end_time: "13:15",
    color: "emerald"
  },
  {
    id: "section-coe444-01",
    CRN: 44411,
    course_code: "COE444",
    semester: "Fall 2026",
    section_number: "01",
    instructor_name: "Dr. Karim Saleh",
    capacity: 34,
    actual_enrolled: 22,
    remaining_seats: 12,
    campus: "Jbeil",
    days: ["Tuesday", "Thursday"],
    room: "Networks Lab 215",
    start_time: "14:00",
    end_time: "15:15",
    color: "violet"
  },
  {
    id: "section-coe491-01",
    CRN: 49122,
    course_code: "COE491",
    semester: "Fall 2026",
    section_number: "01",
    instructor_name: "Dr. Nadine Farah",
    capacity: 24,
    actual_enrolled: 19,
    remaining_seats: 5,
    campus: "Beirut",
    days: ["Wednesday"],
    room: "Innovation Studio",
    start_time: "15:30",
    end_time: "17:30",
    color: "rose"
  },
  {
    id: "section-coe491-02",
    CRN: 49123,
    course_code: "COE491",
    semester: "Fall 2026",
    section_number: "02",
    instructor_name: "Dr. Nadine Farah",
    capacity: 22,
    actual_enrolled: 16,
    remaining_seats: 6,
    campus: "Jbeil",
    days: ["Thursday"],
    room: "Jbeil Innovation Lab",
    start_time: "15:30",
    end_time: "17:30",
    color: "rose"
  },
  {
    id: "section-mth304-01",
    CRN: 30413,
    course_code: "MTH304",
    semester: "Fall 2026",
    section_number: "03",
    instructor_name: "Dr. Leila Mansour",
    capacity: 45,
    actual_enrolled: 36,
    remaining_seats: 9,
    campus: "Jbeil",
    days: ["Tuesday", "Thursday"],
    room: "Science Building 101",
    start_time: "09:00",
    end_time: "10:15",
    color: "amber"
  },
  {
    id: "section-coe430-01",
    CRN: 43008,
    course_code: "COE430",
    semester: "Fall 2026",
    section_number: "01",
    instructor_name: "Dr. Samir Khalil",
    capacity: 36,
    actual_enrolled: 24,
    remaining_seats: 12,
    campus: "Beirut",
    days: ["Monday", "Wednesday"],
    room: "Engineering Hall 310",
    start_time: "12:30",
    end_time: "13:45",
    color: "teal"
  },
  {
    id: "section-coe430-02",
    CRN: 43009,
    course_code: "COE430",
    semester: "Fall 2026",
    section_number: "02",
    instructor_name: "Dr. Samir Khalil",
    capacity: 32,
    actual_enrolled: 20,
    remaining_seats: 12,
    campus: "Jbeil",
    days: ["Tuesday", "Thursday"],
    room: "Jbeil Engineering 214",
    start_time: "12:30",
    end_time: "13:45",
    color: "teal"
  },
  {
    id: "section-coe450-01",
    CRN: 45016,
    course_code: "COE450",
    semester: "Fall 2026",
    section_number: "01",
    instructor_name: "Dr. Joseph Daher",
    capacity: 34,
    actual_enrolled: 26,
    remaining_seats: 8,
    campus: "Jbeil",
    days: ["Tuesday", "Thursday"],
    room: "Computing Lab 226",
    start_time: "10:30",
    end_time: "11:45",
    color: "slate"
  }
];

const mockGeneratedSchedulesTable = [
  {
    generated_schedule_id: 9001,
    email: "student@university.edu",
    crn: 52201,
    score: 0.94,
    total_credits_of_schedule: 12,
    created_at: "2026-04-25T09:30:00",
    saved_name: "Balanced Fall Plan"
  },
  {
    generated_schedule_id: 9001,
    email: "student@university.edu",
    crn: 32107,
    score: 0.94,
    total_credits_of_schedule: 12,
    created_at: "2026-04-25T09:30:00",
    saved_name: "Balanced Fall Plan"
  }
];

const mockImportLogsAdmin = [
  {
    import_id: 701,
    admin_user_id: "admin@university.edu",
    records_inserted: 8,
    records_updated: 2,
    when_rec_updated: "12:40:18",
    import_date: "2026-04-25T00:40:18"
  }
];

const initialAiMessages = [
  {
    id: "assistant-welcome",
    role: "assistant",
    text: "Hi, tell me your credit target, preferred days, or scheduling constraints and I will suggest a clean Fall 2026 plan."
  }
];

function getAiPlanningSelectionId(courseId, campus) {
  return `${courseId}-${normalizeSearchValue(campus)}`;
}

function createAiPlanningSelection(course, campus) {
  return {
    id: getAiPlanningSelectionId(course.course_id, campus),
    course_id: course.course_id,
    course_code: course.course_code,
    course_name: course.course_name,
    credits: course.credits,
    campus,
    campuses: [campus],
    prerequisites: course.prerequisites,
    description: course.description,
    color: course.color
  };
}

/* =========================
   App
========================= */

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [authView, setAuthView] = useState("login");
  const [currentUser, setCurrentUser] = useState(null);
  const [registeredLoginEmail, setRegisteredLoginEmail] = useState("");
  const [authSuccessMessage, setAuthSuccessMessage] = useState("");
  const [activeView, setActiveView] = useState("dashboard");
  const [selectedScheduleCourses, setSelectedScheduleCourses] = useState([]);
  const [aiSelectedCourses, setAiSelectedCourses] = useState([]);
  const [aiMessages, setAiMessages] = useState(initialAiMessages);
  const [aiInputValue, setAiInputValue] = useState("");

  const selectedScheduleCourseIdSet = useMemo(() => {
    return new Set(selectedScheduleCourses.map((course) => course.id));
  }, [selectedScheduleCourses]);

  const aiSelectedCourseIdSet = useMemo(() => {
    return new Set(aiSelectedCourses.map((course) => course.id));
  }, [aiSelectedCourses]);

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [activeView, isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated || !currentUser?.email) {
      return;
    }

    let isCurrent = true;

    async function loadSavedSchedule() {
      try {
        const data = await getApiData("/api/schedules/me", { email: currentUser.email });
        const savedItems = Array.isArray(data.schedule?.items)
          ? data.schedule.items.map(normalizeApiSection)
          : [];

        if (isCurrent) {
          setSelectedScheduleCourses(savedItems);
        }
      } catch (error) {
        console.error("Saved schedule load error:", error.message);
      }
    }

    loadSavedSchedule();

    return () => {
      isCurrent = false;
    };
  }, [isAuthenticated, currentUser?.email]);

  async function handleLogin(email, password) {
    const result = await postAuthRequest("/api/auth/login", { email, password });

    if (!result.success) {
      return result;
    }

    setCurrentUser(result.user);
    setIsAuthenticated(true);
    setActiveView("dashboard");
    setAuthSuccessMessage("");

    return {
      success: true
    };
  }

  async function handleRegister(user) {
    const result = await postAuthRequest("/api/auth/register", user);

    if (!result.success) {
      return result;
    }

    setRegisteredLoginEmail(result.user.email);
    setAuthSuccessMessage(result.message || "Account created. You can now log in with your new credentials.");
    setAuthView("login");

    return {
      success: true
    };
  }

  function handleLogout() {
    setIsAuthenticated(false);
    setCurrentUser(null);
    setActiveView("dashboard");
    setAuthView("login");
    setAiSelectedCourses([]);
    setAiMessages(initialAiMessages);
    setAiInputValue("");
  }

  function handleAddAiPlanningCourse(course, campus) {
    if (!course) {
      return;
    }

    const chosenCampus = campus || course.campuses[0];

    setAiSelectedCourses((currentCourses) => {
      const selectionId = getAiPlanningSelectionId(course.course_id, chosenCampus);

      if (currentCourses.some((selectedCourse) => selectedCourse.id === selectionId)) {
        return currentCourses;
      }

      return [...currentCourses, createAiPlanningSelection(course, chosenCampus)];
    });
  }

  function handleRemoveAiPlanningCourse(selectionId) {
    setAiSelectedCourses((currentCourses) => currentCourses.filter((course) => course.id !== selectionId));
  }

  function handleAddScheduleCourse(course) {
    setSelectedScheduleCourses((currentCourses) => {
      if (currentCourses.some((selectedCourse) => selectedCourse.id === course.id)) {
        return currentCourses;
      }

      const nextCourses = [...currentCourses, course];
      saveScheduleCourses(nextCourses, "Current Schedule").catch((error) => {
        console.error("Saved schedule update error:", error.message);
      });
      return nextCourses;
    });
  }

  function handleRemoveCourse(courseId) {
    setSelectedScheduleCourses((currentCourses) => {
      const nextCourses = currentCourses.filter((course) => course.id !== courseId);
      saveScheduleCourses(nextCourses, "Current Schedule").catch((error) => {
        console.error("Saved schedule update error:", error.message);
      });
      return nextCourses;
    });
  }

  async function saveScheduleCourses(courses, savedName = "AI Balanced Fall Plan") {
    if (!currentUser?.email) {
      return;
    }

    const crns = courses
      .map((course) => Number(course.crn || course.id))
      .filter((crn) => Number.isInteger(crn) && crn > 0);

    await postApiData("/api/schedules/me", {
      email: currentUser.email,
      saved_name: savedName,
      crns
    });
  }

  async function handleApplyAiSchedule(courses) {
    setSelectedScheduleCourses(courses);
    setActiveView("dashboard");
    try {
      await saveScheduleCourses(courses);
    } catch (error) {
      console.error("Saved schedule update error:", error.message);
    }
  }

  function handleSetAiSuggestedSchedule(courses) {
    setSelectedScheduleCourses(courses);
    saveScheduleCourses(courses).catch((error) => {
      console.error("Saved schedule update error:", error.message);
    });
  }

  if (!isAuthenticated) {
    if (authView === "register") {
      return (
        <RegisterPage
          onRegister={handleRegister}
          onBackToLogin={() => {
            setAuthSuccessMessage("");
            setAuthView("login");
          }}
        />
      );
    }

    return (
      <LoginPage
        initialEmail={registeredLoginEmail}
        successMessage={authSuccessMessage}
        onLogin={handleLogin}
        onOpenRegister={() => {
          setAuthSuccessMessage("");
          setAuthView("register");
        }}
      />
    );
  }

  if (activeView === "ai") {
    return (
      <AIChatPage
        selectedCourses={selectedScheduleCourses}
        aiSelectedCourses={aiSelectedCourses}
        aiSelectedCourseIdSet={aiSelectedCourseIdSet}
        onBack={() => setActiveView("dashboard")}
        onAddCourse={handleAddAiPlanningCourse}
        onRemoveAiCourse={handleRemoveAiPlanningCourse}
        onApplySchedule={handleApplyAiSchedule}
        onSetSuggestedSchedule={handleSetAiSuggestedSchedule}
        aiMessages={aiMessages}
        setAiMessages={setAiMessages}
        aiInputValue={aiInputValue}
        setAiInputValue={setAiInputValue}
        currentUser={currentUser}
      />
    );
  }

  return (
    <Dashboard
      selectedCourses={selectedScheduleCourses}
      selectedCourseIdSet={selectedScheduleCourseIdSet}
      onAddCourse={handleAddScheduleCourse}
      onRemoveCourse={handleRemoveCourse}
      onOpenAi={() => setActiveView("ai")}
      onLogout={handleLogout}
      currentUser={currentUser}
    />
  );
}

/* =========================
   Login Page
========================= */

function LoginPage({ initialEmail, successMessage, onLogin, onOpenRegister }) {
  const [email, setEmail] = useState(initialEmail || "");
  const [password, setPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setErrorMessage("");
    setIsSubmitting(true);

    const result = await onLogin(email, password);

    if (!result.success) {
      setErrorMessage(result.message);
      setIsSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-card" aria-label="University Scheduler login">
        <div className="login-brand-panel">
          <div className="brand-mark">
            <GraduationCap size={28} />
          </div>
          <p className="eyebrow">Fall 2026 planning</p>
          <h1>University Scheduler</h1>
          <p className="login-subtitle">AI-powered course planning</p>
          <div className="mini-schedule-preview" aria-hidden="true">
            <div className="mini-header">
              <span>Mon</span>
              <span>Tue</span>
              <span>Wed</span>
            </div>
            <div className="mini-grid">
              <span className="mini-block mini-block-a" />
              <span className="mini-block mini-block-b" />
              <span className="mini-block mini-block-c" />
            </div>
          </div>
          <div className="login-detail-row">
            <span><Sparkles size={14} /> AI schedule scoring</span>
            <span><BadgeCheck size={14} /> Conflict detection</span>
          </div>
        </div>

        <form className="login-form-panel" onSubmit={handleSubmit}>
          <div>
            <p className="eyebrow">Student access</p>
            <h2>Welcome back</h2>
          </div>

          {successMessage && <p className="auth-message success">{successMessage}</p>}
          {errorMessage && <p className="auth-message error">{errorMessage}</p>}

          <label className="input-field">
            <span>Email</span>
            <div>
              <Mail size={18} />
              <input
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                type="email"
                placeholder="student@university.edu"
              />
            </div>
          </label>

          <label className="input-field">
            <span>Password</span>
            <div>
              <KeyRound size={18} />
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                placeholder="Enter password"
              />
            </div>
          </label>

          <div className="auth-action-row">
            <button className="primary-button" type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Logging in..." : "Login"}
              <ArrowLeft size={18} className="button-arrow" />
            </button>
            <button
              className="ghost-button auth-secondary-button"
              type="button"
              onClick={onOpenRegister}
              disabled={isSubmitting}
            >
              Register
            </button>
          </div>

          <p className="login-footnote">Authentication uses PostgreSQL; scheduler course data remains demo for now.</p>
        </form>
      </section>
    </main>
  );
}

/* =========================
   Register Page
========================= */

function RegisterPage({ onRegister, onBackToLogin }) {
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [errorMessage, setErrorMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event) {
    event.preventDefault();
    setErrorMessage("");

    if (!email.trim()) {
      setErrorMessage("Email is required.");
      return;
    }

    if (!username.trim()) {
      setErrorMessage("Username is required.");
      return;
    }

    if (!password) {
      setErrorMessage("Password is required.");
      return;
    }

    if (password !== confirmPassword) {
      setErrorMessage("Passwords do not match.");
      return;
    }

    setIsSubmitting(true);
    const result = await onRegister({ email, username, password });

    if (!result.success) {
      setErrorMessage(result.message);
      setIsSubmitting(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-card" aria-label="University Scheduler registration">
        <div className="login-brand-panel">
          <div className="brand-mark">
            <GraduationCap size={28} />
          </div>
          <p className="eyebrow">Student registration</p>
          <h1>University Scheduler</h1>
          <p className="login-subtitle">Create a demo account for AI-powered course planning</p>
          <div className="mini-schedule-preview" aria-hidden="true">
            <div className="mini-header">
              <span>Mon</span>
              <span>Tue</span>
              <span>Wed</span>
            </div>
            <div className="mini-grid">
              <span className="mini-block mini-block-a" />
              <span className="mini-block mini-block-b" />
              <span className="mini-block mini-block-c" />
            </div>
          </div>
          <div className="login-detail-row">
            <span><User size={14} /> USERS-ready fields</span>
            <span><BadgeCheck size={14} /> Hashed passwords</span>
          </div>
        </div>

        <form className="login-form-panel" onSubmit={handleSubmit}>
          <div>
            <p className="eyebrow">New student account</p>
            <h2>Create account</h2>
          </div>

          {errorMessage && <p className="auth-message error">{errorMessage}</p>}

          <label className="input-field">
            <span>Email</span>
            <div>
              <Mail size={18} />
              <input
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                type="email"
                placeholder="student@university.edu"
              />
            </div>
          </label>

          <label className="input-field">
            <span>Username</span>
            <div>
              <User size={18} />
              <input
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                type="text"
                placeholder="Your name"
              />
            </div>
          </label>

          <label className="input-field">
            <span>Password</span>
            <div>
              <KeyRound size={18} />
              <input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type="password"
                placeholder="Create password"
              />
            </div>
          </label>

          <label className="input-field">
            <span>Confirm Password</span>
            <div>
              <KeyRound size={18} />
              <input
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                type="password"
                placeholder="Confirm password"
              />
            </div>
          </label>

          <div className="auth-action-row">
            <button className="primary-button" type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Creating..." : "Create Account"}
              <CheckCircle2 size={18} />
            </button>
            <button
              className="ghost-button auth-secondary-button"
              type="button"
              onClick={onBackToLogin}
              disabled={isSubmitting}
            >
              Back to Login
            </button>
          </div>

          <p className="login-footnote">Registration creates a PostgreSQL user record with a hashed password.</p>
        </form>
      </section>
    </main>
  );
}

/* =========================
   Dashboard Layout
========================= */

function Dashboard({
  selectedCourses,
  selectedCourseIdSet,
  onAddCourse,
  onRemoveCourse,
  onOpenAi,
  onLogout,
  currentUser
}) {
  const conflictReport = useMemo(() => detectScheduleConflicts(selectedCourses), [selectedCourses]);
  const totalCredits = useMemo(() => {
    return selectedCourses.reduce((sum, course) => sum + course.credits, 0);
  }, [selectedCourses]);
  const totalWeeklyHours = useMemo(() => getWeeklyHours(selectedCourses), [selectedCourses]);

  return (
    <main className="app-shell">
      <Navbar currentUser={currentUser} onLogout={onLogout} />
      <div className="dashboard-grid">
        <aside className="left-sidebar">
          <ScheduleStatusPanel
            selectedCourses={selectedCourses}
            conflictReport={conflictReport}
            totalCredits={totalCredits}
            totalWeeklyHours={totalWeeklyHours}
          />
          <SelectedCoursesPanel selectedCourses={selectedCourses} onRemoveCourse={onRemoveCourse} />
        </aside>

        <section className="center-panel">
          <Timetable
            selectedCourses={selectedCourses}
            conflictReport={conflictReport}
            onRemoveCourse={onRemoveCourse}
          />
        </section>

        <aside className="right-sidebar">
          <ManualSectionsPanel
            selectedCourseIdSet={selectedCourseIdSet}
            onAddCourse={onAddCourse}
          />
        </aside>
      </div>
      <FloatingAIButton onClick={onOpenAi} />
    </main>
  );
}

/* =========================
   Navbar
========================= */

function Navbar({ currentUser, onLogout }) {
  return (
    <header className="top-navbar">
      <div className="navbar-title">
        <div className="navbar-logo">
          <GraduationCap size={24} />
        </div>
        <div>
          <h1>University Scheduler</h1>
          <p>Interactive AI-powered timetable planner</p>
        </div>
      </div>

      <div className="navbar-actions">
        <div className="profile-badge">
          <User size={16} />
          <span>{currentUser?.username || "Scheduler Student"}</span>
        </div>
        <button className="ghost-button" type="button" onClick={onLogout}>
          <LogOut size={16} />
          Logout
        </button>
      </div>
    </header>
  );
}

/* =========================
   Schedule Status Panel
========================= */

function ScheduleStatusPanel({
  selectedCourses,
  conflictReport,
  totalCredits,
  totalWeeklyHours
}) {
  const conflictCount = conflictReport.pairs.length;

  return (
    <div className="sidebar-stack">
      <section className="panel-card">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Schedule Status</p>
            <h2>Fall 2026 Plan</h2>
          </div>
          {conflictCount === 0 ? (
            <CheckCircle2 className="status-icon success" size={22} />
          ) : (
            <AlertTriangle className="status-icon warning" size={22} />
          )}
        </div>

        <div className="metric-list">
          <StatusMetric label="Selected courses" value={selectedCourses.length} />
          <StatusMetric label="Conflicts" value={conflictCount} danger={conflictCount > 0} />
          <StatusMetric label="Total credits" value={totalCredits} />
          <StatusMetric label="Weekly hours" value={totalWeeklyHours} />
        </div>

        {conflictCount > 0 && (
          <div className="warning-strip">
            <AlertTriangle size={18} />
            <div>
              <strong>{conflictCount} conflict detected</strong>
              <span>
                {conflictReport.pairs.map((pair) => pair.days.map((day) => DAY_SHORT_LABELS[day]).join("/")).join(", ")}
              </span>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function StatusMetric({ label, value, danger = false }) {
  return (
    <div className="metric-row">
      <span>{label}</span>
      <strong className={danger ? "danger-text" : ""}>{value}</strong>
    </div>
  );
}

/* =========================
   Timetable Component
========================= */

function Timetable({ selectedCourses, conflictReport, onRemoveCourse }) {
  const timetableInstances = useMemo(() => {
    return getTimetableInstances(selectedCourses, conflictReport.conflictCourseIds);
  }, [selectedCourses, conflictReport.conflictCourseIds]);

  const hourMarkers = Array.from(
    { length: SCHEDULE_END_HOUR - SCHEDULE_START_HOUR + 1 },
    (_, index) => SCHEDULE_START_HOUR + index
  );

  return (
    <section className="timetable-card" aria-label="Weekly timetable">
      <div className="timetable-toolbar">
        <div>
          <p className="eyebrow">Current Semester</p>
          <h2>Fall 2026 Weekly Timetable</h2>
        </div>
        <div className="timetable-badges">
          <span><CalendarDays size={15} /> Monday - Friday</span>
          <span><Clock3 size={15} /> 8:00 AM - 6:00 PM</span>
        </div>
      </div>

      <div className="timetable-scroll">
        <div className="timetable-header-row">
          <div className="time-corner">Time</div>
          {WEEK_DAYS.map((day) => (
            <div className="day-heading" key={day}>
              <span>{DAY_SHORT_LABELS[day]}</span>
              <strong>{day}</strong>
            </div>
          ))}
        </div>

        <div className="timetable-body">
          <div className="time-axis">
            {hourMarkers.map((hour, index) => (
              <span
                key={hour}
                style={{ top: `${(index / (hourMarkers.length - 1)) * 100}%` }}
              >
                {formatTime(`${String(hour).padStart(2, "0")}:00`)}
              </span>
            ))}
          </div>

          <div className="timetable-grid-area">
            <div className="day-column-lines" aria-hidden="true">
              {WEEK_DAYS.map((day) => (
                <span key={day} />
              ))}
            </div>
            <div className="hour-lines" aria-hidden="true">
              {hourMarkers.map((hour, index) => (
                <span
                  key={hour}
                  style={{ top: `${(index / (hourMarkers.length - 1)) * 100}%` }}
                />
              ))}
            </div>

            {timetableInstances.map((instance) => (
              <CourseBlock
                course={instance}
                onRemoveCourse={onRemoveCourse}
                key={instance.instanceId}
              />
            ))}

            {selectedCourses.length === 0 && (
              <div className="empty-timetable-state">
                <CalendarDays size={28} />
                <p>Select courses to build your weekly plan.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

/* =========================
   Course Block
========================= */

function CourseBlock({ course, onRemoveCourse }) {
  const palette = getCoursePalette(course.color);
  const top = ((course.startMinutes - SCHEDULE_START_MINUTES) / SCHEDULE_TOTAL_MINUTES) * 100;
  const height = ((course.endMinutes - course.startMinutes) / SCHEDULE_TOTAL_MINUTES) * 100;
  const columnWidth = 100 / WEEK_DAYS.length;
  const left = course.dayIndex * columnWidth + course.laneIndex * (columnWidth / course.laneCount);
  const width = columnWidth / course.laneCount;

  return (
    <article
      className={`course-block ${course.isConflict ? "is-conflict" : ""}`}
      style={{
        "--course-accent": palette.accent,
        "--course-soft": palette.soft,
        "--course-border": palette.border,
        "--course-text": palette.text,
        top: `${top}%`,
        height: `calc(${height}% - 10px)`,
        left: `calc(${left}% + 8px)`,
        width: `calc(${width}% - 16px)`
      }}
    >
      <button
        className="course-block-delete"
        type="button"
        onClick={(event) => {
          event.stopPropagation();
          onRemoveCourse(course.id);
        }}
        aria-label={`Remove ${course.course_code}`}
      >
        <Trash2 size={12} />
      </button>
      <div className="course-block-topline">
        <strong>{course.course_code}</strong>
        {course.isConflict && <AlertTriangle size={14} />}
      </div>
      <h3>{course.course_name}</h3>
      <p>CRN {course.crn} · {course.instructor}</p>
      <span>{formatTimeRange(course)}</span>
      <span>{course.room}</span>
    </article>
  );
}

/* =========================
   Selected Courses Panel
========================= */

function SelectedCoursesPanel({ selectedCourses, onRemoveCourse }) {
  return (
    <section className="right-panel-section schedule-list-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Selected Courses</p>
          <h2>Your Schedule</h2>
        </div>
        <span className="count-pill">{selectedCourses.length}</span>
      </div>

      <div className="course-card-list">
        {selectedCourses.map((course) => (
          <SelectedCourseCard course={course} onRemoveCourse={onRemoveCourse} key={course.id} />
        ))}

        {selectedCourses.length === 0 && (
          <div className="empty-side-state">
            <BookOpen size={22} />
            <p>No courses selected yet.</p>
          </div>
        )}
      </div>
    </section>
  );
}

function SelectedCourseCard({ course, onRemoveCourse }) {
  const palette = getCoursePalette(course.color);

  return (
    <article className="selected-course-card" style={{ "--course-accent": palette.accent }}>
      <button
        className="icon-button remove-course-button"
        type="button"
        onClick={() => onRemoveCourse(course.id)}
        aria-label={`Remove ${course.course_code}`}
      >
        <Trash2 size={15} />
      </button>

      <div className="course-card-main">
        <span className="course-code-pill">{course.course_code}</span>
        <div>
          <h3>{course.course_name}</h3>
          <p>CRN {course.crn} · Section {course.section}</p>
        </div>
      </div>

      <div className="detail-grid">
        <span><BookOpen size={14} /> {formatCredits(course)}</span>
        <span><User size={14} /> {course.instructor}</span>
        <span><Building2 size={14} /> {course.campus}</span>
        <span><MapPin size={14} /> {course.room}</span>
        <span><CalendarDays size={14} /> {formatDays(course.days)}</span>
        <span><Clock3 size={14} /> {formatTimeRange(course)}</span>
      </div>

      <div className="prerequisite-row">
        <span>Prerequisites</span>
        <strong>{course.prerequisites.join(", ")}</strong>
      </div>
    </article>
  );
}

/* =========================
   Available Courses Panel
========================= */

function AvailableCoursesPanel({ aiSelectedCourseIdSet, onAddCourse }) {
  const [searchQuery, setSearchQuery] = useState("");
  const [campusFilter, setCampusFilter] = useState("All campuses");
  const [openCampusMenuCourseId, setOpenCampusMenuCourseId] = useState(null);
  const [courseCatalog, setCourseCatalog] = useState([]);
  const [isLoadingCourses, setIsLoadingCourses] = useState(false);
  const [courseErrorMessage, setCourseErrorMessage] = useState("");

  useEffect(() => {
    const trimmedSearch = searchQuery.trim();

    if (!trimmedSearch) {
      setCourseCatalog([]);
      setCourseErrorMessage("");
      setIsLoadingCourses(false);
      return undefined;
    }

    const requestId = window.setTimeout(async () => {
      setIsLoadingCourses(true);
      setCourseErrorMessage("");

      try {
        const catalog = await getApiData("/api/courses/catalog", {
          search: trimmedSearch,
          campus: campusFilter === "All campuses" ? "" : campusFilter,
          limit: 100
        });
        setCourseCatalog((Array.isArray(catalog) ? catalog : []).map(normalizeApiCatalogCourse));
      } catch (error) {
        setCourseCatalog([]);
        setCourseErrorMessage(error.message || "Unable to load courses.");
      } finally {
        setIsLoadingCourses(false);
      }
    }, 250);

    return () => window.clearTimeout(requestId);
  }, [campusFilter, searchQuery]);

  return (
    <section className="right-panel-section catalog-panel-card">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Available courses</p>
          <h2>Course Catalog</h2>
        </div>
        <span className="count-pill muted">{courseCatalog.length}</span>
      </div>

      <div className="catalog-controls">
        <label className="catalog-search-field">
          <Search size={17} />
          <input
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search by code or course name..."
          />
        </label>

        <div className="catalog-filter-row">
          <div className="campus-segment" aria-label="Campus filter">
            {["All campuses", "Beirut", "Jbeil"].map((campus) => (
              <button
                className={campusFilter === campus ? "active" : ""}
                type="button"
                key={campus}
                onClick={() => setCampusFilter(campus)}
              >
                {campus}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="available-list">
        {courseCatalog.map((course) => {
          const palette = getCoursePalette(course.color);
          const selectedCampuses = course.campuses.filter((campus) => {
            return aiSelectedCourseIdSet.has(getAiPlanningSelectionId(course.course_id, campus));
          });
          const isFullySelectedForAi = selectedCampuses.length === course.campuses.length;
          const isCampusMenuOpen = openCampusMenuCourseId === course.course_id;

          function handleAddClick() {
            if (course.campuses.length === 1) {
              onAddCourse(course, course.campuses[0]);
              return;
            }

            setOpenCampusMenuCourseId((currentCourseId) => {
              return currentCourseId === course.course_id ? null : course.course_id;
            });
          }

          return (
            <article
              className={`available-course-row ${isFullySelectedForAi ? "is-selected" : ""}`}
              key={course.id}
            >
              <span className="available-accent" style={{ background: palette.accent }} />
              <div className="available-course-inline">
                <h3>{course.course_code}</h3>
                <p>{course.course_name}</p>
                <small title={`Campus: ${course.campus}`}>{course.campus}</small>
              </div>
              <div className="course-add-menu-wrap">
                <button
                  className={`icon-button add-course-button ${isFullySelectedForAi ? "is-selected" : ""}`}
                  type="button"
                  onClick={handleAddClick}
                  disabled={isFullySelectedForAi}
                  aria-label={`Add ${course.course_code}`}
                >
                  {isFullySelectedForAi ? <Check size={16} /> : <Plus size={16} />}
                </button>

                {course.campuses.length > 1 && isCampusMenuOpen && (
                  <div className="campus-choice-menu">
                    {course.campuses.map((campus) => {
                      const selectionId = getAiPlanningSelectionId(course.course_id, campus);
                      const isCampusSelected = aiSelectedCourseIdSet.has(selectionId);

                      return (
                        <button
                          type="button"
                          disabled={isCampusSelected}
                          key={campus}
                          onClick={() => {
                            onAddCourse(course, campus);
                            setOpenCampusMenuCourseId(null);
                          }}
                        >
                          {isCampusSelected ? <Check size={13} /> : <Plus size={13} />}
                          Add {campus}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            </article>
          );
        })}

        {isLoadingCourses && (
          <div className="empty-side-state">
            <Search size={22} />
            <p>Loading courses...</p>
          </div>
        )}

        {!isLoadingCourses && courseErrorMessage && (
          <div className="empty-side-state error-state">
            <AlertTriangle size={22} />
            <p>{courseErrorMessage}</p>
          </div>
        )}

        {!isLoadingCourses && !courseErrorMessage && courseCatalog.length === 0 && (
          <div className="empty-side-state">
            <Search size={22} />
            <p>{searchQuery.trim() ? "No courses found." : "Search by code or course name to view courses."}</p>
          </div>
        )}
      </div>
    </section>
  );
}

function ManualSectionsPanel({ selectedCourseIdSet, onAddCourse }) {
  const [searchQuery, setSearchQuery] = useState("");
  const [campusFilter, setCampusFilter] = useState("Beirut");
  const [selectedDayFilters, setSelectedDayFilters] = useState([]);
  const [availableSections, setAvailableSections] = useState([]);
  const [isLoadingSections, setIsLoadingSections] = useState(false);
  const [sectionErrorMessage, setSectionErrorMessage] = useState("");

  useEffect(() => {
    const trimmedSearch = searchQuery.trim();

    if (!trimmedSearch) {
      setAvailableSections([]);
      setSectionErrorMessage("");
      setIsLoadingSections(false);
      return undefined;
    }

    const requestId = window.setTimeout(async () => {
      setIsLoadingSections(true);
      setSectionErrorMessage("");

      try {
        const sections = await getApiData("/api/courses/sections", {
          search: trimmedSearch,
          days: selectedDayFilters.map((day) => DAY_SHORT_LABELS[day]).join(","),
          campus: campusFilter,
          limit: 50
        });
        setAvailableSections((Array.isArray(sections) ? sections : []).map(normalizeApiSection));
      } catch (error) {
        setAvailableSections([]);
        setSectionErrorMessage(error.message || "Unable to load sections.");
      } finally {
        setIsLoadingSections(false);
      }
    }, 250);

    return () => window.clearTimeout(requestId);
  }, [campusFilter, searchQuery, selectedDayFilters]);

  function toggleDayFilter(day) {
    setSelectedDayFilters((currentDays) => {
      if (currentDays.includes(day)) {
        return currentDays.filter((selectedDay) => selectedDay !== day);
      }

      return [...currentDays, day];
    });
  }

  return (
    <section className="right-panel-section manual-sections-panel">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Manual planning</p>
          <h2>All Sections</h2>
        </div>
        <span className="count-pill muted">{availableSections.length}</span>
      </div>

      <p className="panel-helper-text">Search exact sections and add them directly to the final timetable.</p>

      <label className="catalog-search-field">
        <Search size={17} />
        <input
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          placeholder="Search CRN, course code, course name, or instructor..."
        />
      </label>

      <div className="campus-priority-toggle" aria-label="Campus filter">
        {["Beirut", "Jbeil"].map((campus) => (
          <button
            className={campusFilter === campus ? "active" : ""}
            type="button"
            key={campus}
            onClick={() => setCampusFilter(campus)}
          >
            {campus}
          </button>
        ))}
      </div>

      <div className="day-filter-row" aria-label="Day filters">
        {DAY_FILTERS.map((day) => (
          <button
            className={selectedDayFilters.includes(day.value) ? "active" : ""}
            type="button"
            key={day.value}
            onClick={() => toggleDayFilter(day.value)}
          >
            {day.label}
          </button>
        ))}
      </div>

      <div className="manual-section-list">
        {availableSections.map((course) => {
          const isSelected = selectedCourseIdSet.has(course.id);

          return (
            <ManualSectionCard
              course={course}
              isSelected={isSelected}
              onAddCourse={onAddCourse}
              key={course.id}
            />
          );
        })}

        {!searchQuery.trim() && (
          <div className="empty-side-state">
            <Search size={22} />
            <p>Search CRN, course code, course name, or instructor to view available sections.</p>
          </div>
        )}

        {searchQuery.trim() && isLoadingSections && (
          <div className="empty-side-state">
            <Search size={22} />
            <p>Loading sections...</p>
          </div>
        )}

        {searchQuery.trim() && !isLoadingSections && sectionErrorMessage && (
          <div className="empty-side-state error-state">
            <AlertTriangle size={22} />
            <p>{sectionErrorMessage}</p>
          </div>
        )}

        {searchQuery.trim() && !isLoadingSections && !sectionErrorMessage && availableSections.length === 0 && (
          <div className="empty-side-state">
            <Search size={22} />
            <p>No sections found.</p>
          </div>
        )}
      </div>
    </section>
  );
}

function ManualSectionCard({ course, isSelected, onAddCourse }) {
  const palette = getCoursePalette(course.color);

  return (
    <article className={`manual-section-card ${isSelected ? "is-selected" : ""}`}>
      <span className="available-accent" style={{ background: palette.accent }} />
      <div className="manual-section-content">
        <div className="manual-section-topline">
          <div>
            <h3>{course.course_code}</h3>
            <p>{course.course_name}</p>
          </div>
          <span className="campus-badge">{course.campus}</span>
        </div>

        <div className="manual-section-meta">
          <span>CRN {course.crn} - Sec {course.section}</span>
          <span>{course.instructor}</span>
          <span>{formatDays(course.days)} - {formatTimeRange(course)}</span>
          <span>{course.room}</span>
        </div>
      </div>

      <button
        className={`icon-button add-course-button ${isSelected ? "is-selected" : ""}`}
        type="button"
        onClick={() => onAddCourse(course)}
        disabled={isSelected}
        aria-label={`Add ${course.course_code} section ${course.section}`}
      >
        {isSelected ? <Check size={16} /> : <Plus size={16} />}
      </button>
    </article>
  );
}

/* =========================
   AI Scheduler Button
========================= */

function FloatingAIButton({ onClick }) {
  return (
    <button className="floating-ai-button" type="button" onClick={onClick}>
      <MessageCircle size={20} />
      AI Scheduler
    </button>
  );
}

/* =========================
   AI Scheduler Chat Page
========================= */

function AIChatPage({
  selectedCourses,
  aiSelectedCourses,
  aiSelectedCourseIdSet,
  onBack,
  onAddCourse,
  onRemoveAiCourse,
  onApplySchedule,
  onSetSuggestedSchedule,
  aiMessages,
  setAiMessages,
  aiInputValue,
  setAiInputValue,
  currentUser
}) {
  const chatThreadRef = useRef(null);
  const [isAiResponding, setIsAiResponding] = useState(false);

  const selectedSummary = useMemo(() => {
    return {
      credits: selectedCourses.reduce((sum, course) => sum + course.credits, 0),
      conflicts: detectScheduleConflicts(selectedCourses).pairs.length
    };
  }, [selectedCourses]);

  useEffect(() => {
    const chatThread = chatThreadRef.current;

    if (chatThread) {
      chatThread.scrollTo({
        top: chatThread.scrollHeight,
        behavior: "smooth"
      });
    }
  }, [aiMessages]);

  async function buildAssistantResponse(userText) {
    const planningCourses = aiSelectedCourses.length > 0 ? aiSelectedCourses : selectedCourses;
    const sessionId = currentUser?.id ? `user-${currentUser.id}` : "default";

    if (shouldUseCourseSearchEndpoint(userText, planningCourses)) {
      const result = await postLlmRequest("/chat", {
        message: userText,
        session_id: sessionId
      });

      return {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        text: result.response || "I could not find relevant courses for that request."
      };
    }

    if (!shouldUseScheduleEndpoint(userText, planningCourses)) {
      const result = await postLlmRequest("/chat", {
        message: userText,
        session_id: sessionId
      });

      return {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        text: result.response || "I could not find relevant courses for that request."
      };
    }

    const result = await postLlmRequest("/generate-schedule", {
      query: userText,
      selected_courses: planningCourses,
      session_id: sessionId
    });
    const suggestedCourses = (Array.isArray(result.selected_courses) ? result.selected_courses : [])
      .map(normalizeApiSection);
    const totalCredits = Number(result.total_credits) || suggestedCourses.reduce((sum, course) => sum + course.credits, 0);

    return {
      id: `assistant-${Date.now()}`,
      role: "assistant",
      text: result.explanation || `I created a schedule with ${suggestedCourses.length} courses and ${totalCredits} credits.`,
      suggestedCourses,
      scheduleMeta: {
        saved_name: "AI Balanced Fall Plan",
        score: 1,
        total_credits_of_schedule: totalCredits,
        generated_schedule_id: Date.now()
      }
    };
  }

  async function handleSend() {
    const textToSend = aiInputValue.trim();

    if (!textToSend || isAiResponding) {
      return;
    }

    const userMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      text: textToSend
    };

    setAiMessages((currentMessages) => [...currentMessages, userMessage]);
    setAiInputValue("");
    setIsAiResponding(true);

    const assistantMessage = await buildAssistantResponse(textToSend).catch((error) => ({
      id: `assistant-${Date.now()}`,
      role: "assistant",
      text: error.message || "I could not load matching sections from the course database right now."
    }));

    setAiMessages((currentMessages) => [...currentMessages, assistantMessage]);
    if (assistantMessage.suggestedCourses?.length > 0) {
      onSetSuggestedSchedule(assistantMessage.suggestedCourses);
    }
    setIsAiResponding(false);
  }

  return (
    <main className="ai-page">
      <header className="ai-header">
        <button className="ghost-button" type="button" onClick={onBack}>
          <ArrowLeft size={16} />
          Back to Dashboard
        </button>
        <div>
          <p className="eyebrow">AI Planning Workspace</p>
          <h1>AI Scheduling Assistant</h1>
        </div>
        <div className="ai-header-stats">
          <span>{selectedSummary.credits} current credits</span>
          <span>{selectedSummary.conflicts} conflicts</span>
        </div>
      </header>

      <section className="ai-workspace-grid">
        <section className="chat-panel">
          <div className="chat-panel-heading">
            <div className="chat-title-icon">
              <Bot size={18} />
            </div>
            <div>
              <p className="eyebrow">Conversation</p>
              <h2>AI Assistant</h2>
            </div>
          </div>

          <div className="chat-thread" ref={chatThreadRef}>
            {aiMessages.map((message) => (
              <ChatMessage
                message={message}
                onApplySchedule={onApplySchedule}
                key={message.id}
              />
            ))}
          </div>

          <AIPlanningCoursesPanel
            courses={aiSelectedCourses}
            onRemoveCourse={onRemoveAiCourse}
          />

          <div className="chat-input-row">
            <input
              value={aiInputValue}
              onChange={(event) => setAiInputValue(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  handleSend();
                }
              }}
              placeholder="Ask the AI to optimize credits, days, gaps, or conflicts..."
            />
            <button
              className="primary-button compact-button"
              type="button"
              onClick={() => handleSend()}
              disabled={isAiResponding}
            >
              <Send size={17} />
              {isAiResponding ? "Thinking..." : "Send"}
            </button>
          </div>
        </section>

        <AvailableCoursesPanel
          aiSelectedCourseIdSet={aiSelectedCourseIdSet}
          onAddCourse={onAddCourse}
        />
      </section>
    </main>
  );
}

function AIPlanningCoursesPanel({ courses, onRemoveCourse }) {
  return (
    <section className="ai-planning-courses">
      <div className="ai-planning-heading">
        <div>
          <p className="eyebrow">Courses for AI planning</p>
          <h3>{courses.length} selected</h3>
        </div>
      </div>

      {courses.length === 0 ? (
        <p className="ai-planning-placeholder">Add courses from the catalog for the AI to plan with.</p>
      ) : (
        <div className="ai-course-chip-list">
          {courses.map((course) => (
            <article className="ai-course-chip" key={course.id}>
              <div>
                <strong>{course.course_code}</strong>
                <span>{course.course_name}</span>
                <small>{course.campus}</small>
              </div>
              <button
                className="mini-remove-button"
                type="button"
                onClick={() => onRemoveCourse(course.id)}
                aria-label={`Remove ${course.course_code} from AI planning`}
              >
                <X size={14} />
              </button>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

/* =========================
   Chat Message
========================= */

function ChatMessage({ message, onApplySchedule }) {
  const isAssistant = message.role === "assistant";

  return (
    <article className={`chat-message ${isAssistant ? "assistant" : "user-message"}`}>
      <div className="chat-avatar">
        {isAssistant ? <Bot size={18} /> : <User size={18} />}
      </div>
      <div className="chat-bubble">
        <p>{message.text}</p>
        {message.suggestedCourses?.length > 0 && (
          <SuggestedScheduleCard
            courses={message.suggestedCourses}
            scheduleMeta={message.scheduleMeta}
            onApplySchedule={onApplySchedule}
          />
        )}
      </div>
    </article>
  );
}

/* =========================
   Suggested Schedule Card
========================= */

function SuggestedScheduleCard({ courses, scheduleMeta, onApplySchedule }) {
  const conflicts = detectScheduleConflicts(courses).pairs.length;
  const weeklyHours = getWeeklyHours(courses);

  return (
    <div className="suggested-schedule-card">
      <div className="suggested-heading">
        <div>
          <span>Suggested schedule</span>
          <strong>{scheduleMeta.saved_name}</strong>
        </div>
        <span className="score-pill">{Math.round(scheduleMeta.score * 100)}%</span>
      </div>

      <div className="suggested-stats">
        <span>{scheduleMeta.total_credits_of_schedule} credits</span>
        <span>{weeklyHours} weekly hours</span>
        {conflicts > 0 && <span>{conflicts} conflicts</span>}
      </div>

      <div className="suggested-course-list">
        {courses.map((course) => (
          <div key={course.id}>
            <span>{course.course_code}</span>
            <strong>{course.course_name}</strong>
            <small>{formatDays(course.days)} · {formatTimeRange(course)}</small>
          </div>
        ))}
      </div>

      <button className="primary-button full-width-button" type="button" onClick={() => onApplySchedule(courses)}>
        <CheckCircle2 size={18} />
        Apply AI Schedule
      </button>
    </div>
  );
}
