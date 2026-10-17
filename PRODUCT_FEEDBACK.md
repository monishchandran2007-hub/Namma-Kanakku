# KiranaFlow - Product & Developer Feedback

> **Subject**: Constructive evaluation of the Model Context Protocol (MCP) Python SDK (`mcp==2.3.0`) and the Alexa+ Developer Experience.
>
> **Author**: KiranaFlow Team (Alexa+ Track, Amazon Developer Hackathon 2026).

---

## 1. What Worked Extremely Well

### 1.1 Streamable HTTP as a First-Class Citizen
The decision in the November 2025 MCP specification to standardize on **Streamable HTTP** alongside stdio is an enormous step forward. It allows developers to build and host standard web microservices using familiar Python frameworks (Starlette, FastAPI, Uvicorn) that can be deployed to any cloud container or serverless platform without specialized stdio bridges.

### 1.2 Deterministic Protocol Latency
The Python SDK's underlying async JSON-RPC pipeline delivers exceptional performance. In our 50-call benchmark:
- **Median latency (p50)**: **12.92 ms**
- **95th percentile (p95)**: **21.86 ms**
- **Average**: **14.63 ms**
This leaves virtually all conversational latency budget to network transit and speech synthesis, allowing near-instant voice interactions.

### 1.3 Clean Separation of Concerns
Building KiranaFlow highlighted the power of decoupling:
- **Alexa+** acts as the multilingual acoustic and natural language front-end (handling noisy ambient audio, Indian accent variations, and slot extraction).
- **KiranaFlow MCP Server** acts as the deterministic ledger (doing the arithmetic, enforcing business rules, ensuring database integrity, and preventing hallucinated transactions).

---

## 2. Opportunities for SDK Improvement

### 2.1 First-Class Decorator Support for Tool Metadata & MCP Apps
Currently, adding custom metadata (such as `_meta.ui.resourceUri` for MCP Apps) requires either manually modifying the underlying tool definition or wrapping tool return objects.
**Recommendation**:
Add direct support in the `@mcp.tool()` decorator:
```python
@mcp.tool(
    name="log_credit_entry",
    description="...",
    ui_resource_uri="ui://khata-card",
    category="ledger"
)
async def log_credit_entry(...):
    ...
```

### 2.2 Python-Native MCP Inspector
The official MCP Inspector (`@modelcontextprotocol/inspector`) is built on Node.js / npm. In pure Python environments, developers must switch tooling environments to run visual inspect tests.
**Recommendation**:
Provide a lightweight `mcp inspect <server_url>` command in the Python SDK that spins up a local browser UI to trigger tools, inspect JSON-RPC payloads, and preview embedded UI resources.

### 2.3 Documentation & Migration Guides for SDK 2.x
The upgrade from `FastMCP` (`mcp.server.fastmcp`) to `MCPServer` (`mcp.server.mcpserver`) in SDK 2.x is a welcome architectural cleanup, but many existing examples and docs still reference the deprecated paths.
**Recommendation**:
Add a prominent "Upgrading to 2.x" guide in the GitHub repository README and docstrings explaining the module reorganization.

---

## 3. Recommendations for the Alexa+ Developer Ecosystem

### 3.1 Developer Sandbox for Multilingual Code-Mixed Speech
In everyday commerce across India, shopkeepers communicate in mixed dialects:
- **Tanglish** (Tamil + English): *"Ramesh teacher ku oru packet thayir eduthuko"* (Take one packet curd for Ramesh teacher).
- **Hinglish** (Hindi + English): *"Sharma ji ke khate mein 2 packet doodh daal do"*.

A simulator feature where developers can test simulated Tanglish / Hinglish slot-extraction payloads against their MCP server endpoints would drastically improve confidence before physical device deployment.

### 3.2 Formal Protocol Support for "Discretion / Privacy" Mode
In retail point-of-sale and financial contexts, voice assistants need a recognized design pattern for **Privacy Boundaries**:
- What gets spoken into the room (audio output).
- What gets rendered silently on display (screen-only notes and UI cards).

Formalizing this distinction in the Alexa+ tool schema specifications (e.g. `discreet_voice: boolean` or distinct `spoken_text` vs `visual_payload` contract) would establish an industry best practice for retail voice software.

### 3.3 Explicit Multi-Item Batching & Transactional Boundaries in Tool Schemas
When a customer orders multiple items at a counter (*"two curds and one packet oil"*), standard conversational pipelines sometimes trigger multiple independent tool invocations. If tool call 1 succeeds and tool call 2 fails, the ledger is left partially updated.
**Recommendation**:
Encourage or provide native schema conventions in the Alexa+ developer toolkit for atomic multi-event payloads (`events: list`), ensuring assistants pass composite orders in a single transactional turn rather than piecemeal.

