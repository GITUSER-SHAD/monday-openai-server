require("dotenv").config();
const express = require("express");
const axios = require("axios");

const app = express();
app.use(express.json());

// Simple health check
app.get("/", (req, res) => res.send("OK"));
app.get("/webhook", (req, res) => res.send("WEBHOOK OK"));

app.post("/webhook", async (req, res) => {
  // Monday verification handshake
  if (req.body && req.body.challenge) {
    return res.json({ challenge: req.body.challenge });
  }

  // Acknowledge immediately
  res.status(200).send("OK");

  try {
    const event = req.body?.event;
    if (!event) {
      console.log("No event payload:", req.body);
      return;
    }

    const itemId = event.pulseId || event.itemId;
    if (!itemId) {
      console.log("No itemId/pulseId found:", req.body);
      return;
    }

    // 1) Read item name from Monday
    const mondayResp = await axios.post(
      "https://api.monday.com/v2",
      {
        query: `
          query {
            items(ids: ${itemId}) {
              id
              name
            }
          }
        `,
      },
      { headers: { Authorization: process.env.MONDAY_API_KEY } }
    );

    const itemName = mondayResp.data?.data?.items?.[0]?.name || "(no name)";

    // 2) Ask OpenAI
    const openaiResp = await axios.post(
      "https://api.openai.com/v1/chat/completions",
      {
        model: "gpt-4o-mini",
        messages: [
          {
            role: "user",
            content:
              `Rewrite/summarize this Monday item into a professional, actionable note.\n\n` +
              `Item: ${itemName}\n\n` +
              `Return 3 bullets + 1 short summary sentence.`,
          },
        ],
      },
      { headers: { Authorization: `Bearer ${process.env.OPENAI_API_KEY}` } }
    );

    const aiText = openaiResp.data?.choices?.[0]?.message?.content || "";

    // Escape for Monday GraphQL string
    const safeBody = aiText
      .replace(/\\/g, "\\\\")
      .replace(/"/g, '\\"')
      .replace(/\n/g, "\\n");

    // 3) Post result back to Monday as an Update
    await axios.post(
      "https://api.monday.com/v2",
      {
        query: `
          mutation {
            create_update(item_id: ${itemId}, body: "${safeBody}") { id }
          }
        `,
      },
      { headers: { Authorization: process.env.MONDAY_API_KEY } }
    );

    console.log(`Posted AI update to item ${itemId}`);
  } catch (err) {
    console.error("Webhook processing error:", err?.response?.data || err.message);
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));
