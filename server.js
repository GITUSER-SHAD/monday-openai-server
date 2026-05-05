require("dotenv").config();
const express = require("express");
const axios = require("axios");

const app = express();
app.use(express.json());

app.get("/", (req, res) => res.send("OK"));
app.get("/webhook", (req, res) => res.send("WEBHOOK OK"));

app.post("/webhook", async (req, res) => {
  console.log("=== WEBHOOK RECEIVED ===");
  console.log("Body:", JSON.stringify(req.body, null, 2));

  res.status(200).send("OK");

  try {
    const itemName = req.body.itemName || req.body.title || "Untitled from Plaud";
    console.log("Creating item in ClickUp:", itemName);

    // Create item in ClickUp
    await axios.post(
      "https://api.clickup.com/api/v2/list/6-901416156788-1/task",
      {
        name: itemName,
        description: req.body.transcript || "",
        priority: 3, // Medium
        status: "New"
      },
      {
        headers: {
          Authorization: process.env.CLICKUP_API_KEY
        }
      }
    );

    console.log("✅ Item created in ClickUp");
    console.log("=== END ===");
  } catch (err) {
    console.error("ERROR:", err.response?.data || err.message);
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));