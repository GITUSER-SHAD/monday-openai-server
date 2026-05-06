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
    
    // Extract title from Plaud's long string format
    let rawText = Object.values(body)[0] || "";
    let title = "New Plaud Note";

    if (rawText.includes("Title:")) {
      title = rawText.split("Title:")[1].split("\n")[0].trim();
    } else if (rawText.length > 10) {
      title = rawText.substring(0, 80) + "...";
    }

    // Create item in ClickUp
    await axios.post(
      "https://api.clickup.com/api/v2/list/901416156788/task",
      {
        name: title,
        description: rawText,
        priority: 3
      },
      {
        headers: { Authorization: process.env.CLICKUP_API_KEY }
      }
    );

    console.log("✅ Item created:", title);
    console.log("=== END ===");
  } catch (err) {
    console.error("ERROR:", err.response?.data || err.message);
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));