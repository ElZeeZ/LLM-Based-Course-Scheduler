import express from "express";
import {
  getCourseCatalog,
  getCourseHealth,
  getExactSectionsForCourses,
  getSections,
  getSectionsForCourses
} from "../services/courseService.js";

const router = express.Router();

function parseDays(days) {
  return String(days || "")
    .split(",")
    .map((day) => day.trim())
    .filter(Boolean);
}

router.get("/health", async (_request, response) => {
  try {
    const health = await getCourseHealth();
    response.json({ success: true, ...health });
  } catch (error) {
    console.error("Course health error:", error.message);
    response.status(500).json({ success: false, message: "Unable to query course tables." });
  }
});

router.get("/sections", async (request, response) => {
  try {
    const sections = await getSections({
      search: request.query.search,
      days: parseDays(request.query.days),
      campus: request.query.campus,
      limit: request.query.limit
    });

    response.json(sections);
  } catch (error) {
    console.error("Sections retrieval error:", error.message);
    response.status(500).json({ success: false, message: "Unable to load course sections." });
  }
});

router.post("/sections/batch", async (request, response) => {
  try {
    const sections = await getSectionsForCourses({
      courses: request.body.courses,
      courseCodes: request.body.course_codes,
      searchTerms: request.body.search_terms,
      campus: request.body.campus,
      limitPerCourse: request.body.limit_per_course
    });

    response.json({ success: true, sections });
  } catch (error) {
    console.error("Batch sections retrieval error:", error.message);
    response.status(500).json({ success: false, message: "Unable to load course sections." });
  }
});

router.post("/sections/exact", async (request, response) => {
  try {
    const sections = await getExactSectionsForCourses({
      courses: request.body.courses,
      courseCodes: request.body.course_codes,
      crns: request.body.crns,
      campus: request.body.campus,
      limitPerCourse: request.body.limit_per_course
    });

    response.json({ success: true, sections });
  } catch (error) {
    console.error("Exact sections retrieval error:", error.message);
    response.status(500).json({ success: false, message: "Unable to load exact course sections." });
  }
});

router.get("/catalog", async (request, response) => {
  try {
    const catalog = await getCourseCatalog({
      search: request.query.search,
      campus: request.query.campus,
      limit: request.query.limit
    });

    response.json(catalog);
  } catch (error) {
    console.error("Catalog retrieval error:", error.message);
    response.status(500).json({ success: false, message: "Unable to load course catalog." });
  }
});

export default router;
