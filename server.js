require("dotenv").config();
const express = require("express");
const axios = require("axios");

const app = express();
app.use(express.json());

app.get("/", (req, res) => res.send("OK"));
app.get("/webhook", (req, res) => res.send("WEBHOOK OK"));

app.post("/webhook", async (req, res) => {
  console.log("=== WEBHOOK RECEIVED ===");
  res.status(200).send("OK");

  try {
    const body = req.body;
    let rawText = Object.values(body)[0] || "";

    // Grok Analysis + Calendar Drafting
    const grokResponse = await axios.post(
      "https://api.x.ai/v1/chat/completions",
      {
        model: "grok-2",
        messages: [
          {
            role: "system",
            content: `You are an expert executive assistant. Analyze the voice note and return a JSON object with these fields:
{
  "clickup_title": "Clear, actionable title for ClickUp (max 80 chars)",
  "clickup_description": "Professional summary + next actions",
  "priority": "Low" | "Medium" | "High" | "Critical",
  "area": "Personal" | "Work" | "Health" | "Finance" | "Home" | "Travel" | "Relationships" | "Rental",
  "calendar_event": {
    "title": "Calendar event title",
    "description": "Event description",
    "suggested_date": "YYYY-MM-DD or null",
    "suggested_time": "HH:MM or null",
    "duration_minutes": 30 | 60 | 90 | 120
  }
}`
          },
          {
            role: "user",
            content: rawText
          }
        ],
        response_format: { type: "json_object" }
      },
      {
        headers: {
          Authorization: `Bearer ${process.env.XAI_API_KEY}`,
          "Content-Type": "application/json"
        }
      }
    );

    const analysis = JSON.parse(grokResponse.data.choices[0].message.content);
    console.log("Grok Analysis:", analysis);

    // Create ClickUp item
    await axios.post(
      "https://api.clickup.com/api/v2/list/901416156788/task",
      {
        name: analysis.clickup_title,
        description: analysis.clickup_description,
        priority: analysis.priority === "Critical" ? 1 : analysis.priority === "High" ? 2 : 3
      },
      {
        headers: { Authorization: process.env.CLICKUP_API_KEY }
      }
    );

    console.log("✅ Smart item created:", analysis.clickup_title);
  } catch (err) {
    console.error("ERROR:", err.response?.data || err.message);
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));