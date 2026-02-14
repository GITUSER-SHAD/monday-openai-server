require("dotenv").config();
const express = require("express");
const axios = require("axios");

const app = express();
app.use(express.json());

app.get("/", (req, res) => res.send("OK"));

app.post("/webhook", async (req, res) => {
  // Monday webhook verification step:
  if (req.body && req.body.challenge) {
    return res.json({ challenge: req.body.challenge });
  }

  // Acknowledge immediately
  res.status(200).send("OK");

  // For now, just log what Monday sends
  try {
    console.log("Webhook received:", JSON.stringify(req.body, null, 2));
  } catch (e) {
    console.log("Webhook received (could not stringify).");
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));
