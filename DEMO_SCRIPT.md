# KiranaFlow - 3-Minute Video Demo Script 🎙️🏪

> **Video Duration**: 3 minutes (180 seconds)
> 
> **Format**: Split screen (Left: Shop counter camera simulation with physical goods / Echo Show display; Right: Live screen recording showing MCP Apps widget `ui://khata-card` and terminal / ledger dashboard).
> 
> **Audio Track**: Natural ambient shop sound, clean voiceovers, crisp Alexa+ responses.

---

## ⏱️ [00:00 - 00:30] Act 1: The Hook (The Real Problem in Indian Kirana)

**Visual**:
Close-up of a crowded Indian kirana store counter. Stacks of dal, rice, milk packets. Customers waiting shoulder-to-shoulder. A shopkeeper balancing a paper notebook (*khata*) and a pen with one hand while packing groceries with the other.

**Voiceover / Narrator (0:00 - 0:15)**:
> *"Across India, over 12 million neighbourhood kirana stores run on trust and daily credit. But at a packed counter, writing in a paper notebook is slow, voice assistants blab customers' private debts aloud to everyone standing nearby, and half the orders are in mixed Tanglish."*

**Visual (0:15 - 0:30)**:
Narrator taps the counter next to an Echo Show displaying the **KiranaFlow** widget.
> *"Meet **KiranaFlow**: a privacy-first voice khata for Alexa+ that learns your shop's dialect, keeps your customers' debts strictly confidential, and never guesses with money."*

---

## ⏱️ [00:30 - 01:10] Act 2: Multilingual Speed & The Discretion Rule

**Scene Setup**:
A regular customer, Ramesh Teacher, walks up. Several other customers stand behind him.

**Shopkeeper (Speaking to Alexa+) (0:30 - 0:36)**:
> *"Alexa, Ramesh teacher ku oru packet thayir eduthuko."*
*(Tanglish: Take one packet of curd for Ramesh teacher)*

**Alexa+ / KiranaFlow Response (0:36 - 0:43)**:
> *"Logged 1 packet Curd 500ml for 35 rupees to Ramesh Teacher. Say undo if that's wrong."*

**Visual on Echo Show Screen / Widget (0:43 - 0:58)**:
- The **KiranaFlow Khata Card** instantly lights up with an itemized receipt:
  - `1 packet Curd 500ml — Rs 35`
  - Itemized Total: `Rs 35`
- A discreet visual badge appears: `⚠️ Unpaid for 34 days`.
- **Narrator Highlights the Discretion Safety Rule**:
  > *"Notice what Alexa DID NOT say. Even though Ramesh has an overdue balance, Alexa spoke only the item and the price into the crowded room. His outstanding balance and overdue badge stay strictly private on the shopkeeper's screen. Trust remains intact."*

**Shopkeeper (Private Balance Query) (0:58 - 01:10)**:
*(Ramesh steps away; shopkeeper checks the balance privately)*
> **Shopkeeper**: *"Alexa, what is Ramesh Teacher's balance?"*
> **Alexa+**: *"Ramesh Teacher's current unpaid balance is 3,485 rupees. Credit limit is 5,000 rupees. Oldest unpaid entry is 34 days ago."*

---

## ⏱️ [01:10 - 01:45] Act 3: Instant Reversible Undo & Disambiguation Safety

**Shopkeeper (Mistake & Undo Test) (01:10 - 01:25)**:
> **Shopkeeper**: *"Alexa, put 5 kg Toor Dal on Priya Madam's khata."*
> **Alexa+**: *"Logged 5 kg Toor Dal for 775 rupees to Priya Madam. Say undo if that's wrong."*
> **Shopkeeper**: *"Alexa, undo that!"*
> **Alexa+**: *"Undid the last credit entry of 775 rupees for Priya Madam. Customer balance restored."*

**Visual (01:25 - 01:35)**:
Screen shows the live ledger updating instantly: sequence number `seq` strictly rolled back, total balance recalculated with zero manual ledger math.

**Shopkeeper (Disambiguation Test) (01:35 - 01:45)**:
> **Shopkeeper**: *"Alexa, add oil to Suresh's khata."*
> **Alexa+**: *"Which oil did Suresh take? We have Sunflower Oil 1L, Groundnut Oil 1L, or Gingelly Oil 500ml."*
> **Narrator**: *"KiranaFlow never guesses with pricing. Generic terms pause for clarification—zero rows are written until confirmed."*

---

## ⏱️ [01:45 - 02:20] Act 4: Voice Data-Ownership & Wholesale Intelligence

**Voice Learning (01:45 - 02:00)**:
> **Shopkeeper**: *"Alexa, teach alias: call Curd pasu thayir."*
> **Alexa+**: *"Got it. I've linked 'pasu thayir' to Curd 500ml."*
> **Shopkeeper**: *"Alexa, update Toor Dal price to 160 rupees."*
> **Alexa+**: *"Updated price for Toor Dal from 155 to 160 rupees per kg."*

**Wholesale Margin Calculator (02:00 - 02:20)**:
*(Sales rep brings a wholesale price offer)*
> **Shopkeeper**: *"Alexa, wholesale quote: Toor Dal at 135 rupees for 10 kg."*
> **Alexa+**: *"For Toor Dal, wholesale quote is 135 rupees versus your current retail price of 160 rupees. That's a 15.6% margin, or 25 rupees profit per kg. Total profit on 10 kg will be 250 rupees."*

---

## ⏱️ [02:20 - 02:45] Act 5: Architecture & Real Performance

**Visual**:
Architecture diagram on screen highlighting:
- **Streamable HTTP MCP protocol** running at `/mcp`.
- **Zero external LLMs** inside the server—100% deterministic SQLite arithmetic.
- Latency benchmark chart:
  - **Median Latency (p50)**: **12.92 ms**
  - **95th Percentile (p95)**: **21.86 ms**
  - **36 passing automated tests**

**Narrator (02:20 - 02:45)**:
> *"KiranaFlow is built on the official Model Context Protocol using modern Streamable HTTP. It executes with a verified median latency under 13 milliseconds, running completely locally on lightweight Python without expensive database or third-party LLM dependencies."*

---

## ⏱️ [02:45 - 03:00] Act 6: The Shopkeeper Voice & Call to Action

**Authentic Kirana Perspective (02:45 - 02:53)**:
> **[SHOPKEEPER QUOTE]**
> *"In our shop, we cannot keep customers waiting while typing on a computer. And we cannot embarrass our elders by shouting their balance across the counter. KiranaFlow hears what we say in our own words, keeps our customers' dignity safe, and never makes mistakes with our cash."*

**Closing Splash Screen (02:53 - 03:00)**:
- **KiranaFlow**
- *Alexa+ Track — Amazon Developer Hackathon 2026*
- Open-Source MIT License
- Full code, benchmark scripts, and documentation on GitHub: `https://github.com/your-username/kiranaflow`
