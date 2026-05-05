require("dotenv").config();
const express = require("express");
const axios = require("axios");

const app = express();
app.use(express.json());

app.get("/", (req, res) => res.send("OK"));
app.get("/webhook", (req, res) => res.send("WEBHOOK OK"));

app.post("/webhook", async (req, res) => {
  if (req.body && req.body.challenge) {
    return res.json({ challenge: req.body.challenge });
  }

  res.status(200).send("OK");

  try {
    const event = req.body?.event;
    if (!event) return;

    const itemId = event.pulseId || event.itemId;
    if (!itemId) return;

    const mondayResp = await axios.post(
      "https://api.monday.com/v2",
      {
        query: `query { items(ids: ${itemId}) { name } }`,
      },
      { headers: { Authorization: process.env.MONDAY_API_KEY } }
    );

    const itemName = mondayResp.data?.data?.items?.[0]?.name || "Untitled";

    const openaiResp = await axios.post(
      "https://api.openai.com/v1/chat/completions",
      {
        model: "gpt-4o-mini",
        messages: [
          {
            role: "system",
            content: `You are a helpful assistant for a roofing and building envelope consultant.

Turn the following voice note title into:
- A short professional summary (1-2 sentences)
- 3 clear, actionable next steps

Keep it concise and practical.`
          },
          {
            role: "user",
            content: itemName
          }
        ]
      },
      { headers: { Authorization: `Bearer ${process.env.OPENAI_API_KEY}` } }
    );

    const aiText = openaiResp.data.choices[0].message.content;
    const safeBody = aiText.replace(/\\/g, "\\\\").replace(/"/g, '\\"').replace(/\n/g, "\\n");

    await axios.post(
      "https://api.monday.com/v2",
      {
        query: `
          mutation {
            create_update(item_id: ${itemId}, body: "${safeBody}") { id }
          }
        `
      },
      { headers: { Authorization: process.env.MONDAY_API_KEY } }
    );

    console.log(`✅ Phase 1 update posted for item ${itemId}`);

  } catch (err) {
    console.error("Error:", err?.response?.data || err.message);
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));