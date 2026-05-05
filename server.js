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

    console.log("Item Name:", itemName);

    // TODO: Add ClickUp creation logic here later

    console.log("=== END ===");
  } catch (err) {
    console.error("ERROR:", err.message);
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));