import express from "express";
import { getSavedScheduleForUser, saveScheduleForUser } from "../services/scheduleService.js";

const router = express.Router();

router.get("/me", async (request, response) => {
  try {
    const result = await getSavedScheduleForUser(request.query.email);

    if (!result.ok) {
      return response.status(result.status).json({
        success: false,
        message: result.message
      });
    }

    return response.json({
      success: true,
      schedule: result.schedule
    });
  } catch (error) {
    console.error("Saved schedule retrieval error:", error.message);
    return response.status(500).json({
      success: false,
      message: "Unable to load the saved schedule."
    });
  }
});

router.post("/me", async (request, response) => {
  try {
    const result = await saveScheduleForUser({
      email: request.body.email,
      savedName: request.body.saved_name,
      crns: request.body.crns
    });

    if (!result.ok) {
      return response.status(result.status).json({
        success: false,
        message: result.message
      });
    }

    return response.json({
      success: true,
      message: "Schedule saved successfully.",
      schedule: result.schedule
    });
  } catch (error) {
    console.error("Saved schedule update error:", error.message);
    return response.status(500).json({
      success: false,
      message: "Unable to save the schedule."
    });
  }
});

export default router;
