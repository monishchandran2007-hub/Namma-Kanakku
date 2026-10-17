# Namma-Kanakku (நம்ம கணக்கு) - 3-Minute Video Demo Script 🎙️🏪

> **Video Duration**: Under 3 minutes (178 seconds)  
> **Format**: Split Screen (Left: Kirana counter simulation with physical items and Alexa+ Echo Show; Right: Pure ASGI Counter Screen at `/` and live `ui://khata-card` MCP Apps widget)  
> **Audio**: Ambient Chennai/Bengaluru maligai shop atmosphere, clear spoken Tanglish, clean Alexa+ speech.

---

## ⏱️ [00:00 - 00:30] Act 1: The Hook (The Real Problem at the Counter)

**Visual**:
Close-up of a busy neighbourhood kirana counter in Chennai. Stacks of toor dal, ponni rice, packets of curd and sunflower oil. Customers standing shoulder-to-shoulder. The shopkeeper's hands are dusty from weighing dal on a scale. A regular says *"kanakkula ezhuthikonga"* (write it on my account).

**Voiceover / Narrator (0:00 - 0:18)**:
> *"At a busy kirana counter, the shopkeeper's hands are full: weighing dal, pouring oil, counting change. Writing in an app means wiping hands, unlocking a phone, searching a name, and typing. So entries get postponed, and small debts get forgotten. And worse—ordinary voice assistants shout customers' private debts aloud to everyone standing in line."*

**Visual (0:18 - 0:30)**:
Narrator gestures to the counter screen showing **Namma-Kanakku**:
> *"Meet **Namma-Kanakku** (நம்ம கணக்கு): an Alexa+ MCP voice khata that understands the shop's natural language, keeps customer debts strictly private, and never guesses with money."*

---

## ⏱️ [00:30 - 01:10] Act 2: Multilingual Speed & The Discretion Rule

**Scene Setup**:
A regular customer, Karthik from Apartment 3B, steps up to the counter. Behind him, another customer waits.

**Shopkeeper (Speaking naturally to Alexa+) (0:30 - 0:37)**:
> *"Alexa, Karthik 3B ku rendu thayir and oru kadala ennai, udhaar."*  
> *(Tanglish: For Karthik 3B, two curds and one groundnut oil, on credit)*

**Alexa+ / Namma-Kanakku Spoken Response (0:37 - 0:44)**:
> *"Logged 2 packet Curd 500ml, 1 packet Groundnut Oil 1L for Karthik 3B, total 260 rupees. Say undo if that's wrong."*

**Visual on Counter Screen & Echo Show Widget (0:44 - 0:58)**:
- The **Khata Card** (`ui://khata-card`) displays the itemized receipt:
  - `2 packet Curd 500ml — Rs 70`
  - `1 packet Groundnut Oil 1L — Rs 190`
  - `Total: Rs 260`
- Inventory stock updates automatically: Curd (-2), Groundnut Oil (-1).
- **Narrator Highlights the Discretion Safety Rule**:
  > *"Notice what Alexa DID NOT say. Even though Karthik had an existing balance, Alexa spoke ONLY the items and the bill amount into the crowded room. His total debt was never broadcast. Trust and dignity are preserved."*

**Shopkeeper (Private Balance Query) (0:58 - 01:10)**:
*(Karthik steps away; shopkeeper checks his ledger)*
> **Shopkeeper**: *"Alexa, what is Karthik 3B's balance?"*  
> **Alexa+**: *"Karthik 3B's current balance is 360 rupees."*  
> *(Spoken balance is permitted ONLY on explicit shopkeeper query)*

---

## ⏱️ [01:10 - 01:45] Act 3: Quiet Credit Check & Morning Brief

**Quiet Credit Check (01:10 - 01:25)**:
*(Ramesh Teacher, who has an overdue balance of 35 days, asks for a 500 rupee purchase)*
> **Shopkeeper**: *"Alexa, credit check for Ramesh Teacher for 500 rupees."*  
> **Alexa+ (Speaks aloud)**: *"Please check the screen."*  
> *(Narrator: "Alexa speaks STRICTLY 'Please check the screen.' Not a single number is spoken aloud.")*

**Visual on Counter Screen (01:25 - 01:32)**:
- High-visibility amber card displays privately to shopkeeper:  
  `Credit Check Warning for Ramesh Teacher: Unpaid for 35 days (Balance: Rs 450). Dues would be Rs 950 / Limit Rs 2000.`

**Morning Brief (01:32 - 01:45)**:
> **Shopkeeper**: *"Alexa, morning brief."*  
> **Alexa+**: *"Good morning. You have 2 overdue accounts and 1 item low on stock."*  
> *(Audible counts only! Full customer names and overdue days go to screen notes only.)*

---

## ⏱️ [01:45 - 02:20] Act 4: Reversible Undo, Habit Learning & Profit Tracking

**Instant Reversible Undo (01:45 - 02:00)**:
> **Shopkeeper**: *"rendu thayir cash"*  
> **Alexa+**: *"Cash sale of 70 rupees logged. Say undo if that's wrong."*  
> **Shopkeeper**: *"Aiyyo thappu, undo pannu!"* *(Oh mistake, undo that!)*  
> **Alexa+**: *"Undone last entry. Say undo if that's wrong."*  
> *(Screen shows inventory restored +2 curd, sequence rolled back cleanly.)*

**Habit Learning & Dialect Teaching (02:00 - 02:10)**:
> **Shopkeeper**: *"Alexa, remember pasu thayir means Curd 500ml."*  
> **Alexa+**: *"I've linked 'pasu thayir' to Curd 500ml for your shop."*

**Today's Business Summary & Gross Profit (02:10 - 02:20)**:
> **Shopkeeper**: *"Alexa, today's summary."*  
> **Alexa+**: *"Today: Cash sales 160 rupees, credit 330 rupees, payments collected 200 rupees, estimated gross profit 85 rupees."*  
> *(Built-in wholesale cost tracking computes real gross profit automatically!)*

---

## ⏱️ [02:20 - 02:45] Act 5: Architecture & Real Performance

**Visual**:
Architecture graphic on screen:
- **Official Model Context Protocol (Streamable HTTP /mcp)**.
- **Pure ASGI Counter Screen** at `/` (zero Gradio, zero dev terms like "tab 1" or "Run:").
- **74 passing automated tests** covering discretion, atomicity, habits, and inventory.
- Benchmark:
  - **Median Latency (p50)**: **12.92 ms**
  - **95th Percentile (p95)**: **21.86 ms**
  - **100% Deterministic SQLite arithmetic** (no LLM in the accounting path).

---

## ⏱️ [02:45 - 02:58] Act 6: The Shopkeeper Voice & Close

**Authentic Kirana Perspective (02:45 - 02:53)**:
> **Real Shopkeeper Feedback**:
> *"Enga kadaila kai eppavum ennaiyum paruppuma irukkum. Customer kitta balance-ah sathama solla koodadhu. Voice-la solli screen-la paatha dhaan mariyaadhai."*
> *(In our shop, hands are always covered in oil and dal. We must never shout a customer's balance aloud. Speaking it by voice and seeing it on screen is what keeps respect.)*

**Closing Splash Screen (02:53 - 02:58)**:
- **Namma-Kanakku (நம்ம கணக்கு)**
- *Alexa+ Track — Build, Ship, Shape: Amazon Developer Hackathon 2026*
- Open-Source MIT License
- Repo: `https://github.com/monishchandran2007-hub/Namma-Kanakku`
- Live Space: `https://nnnneek123-namma-kanakku.hf.space`
