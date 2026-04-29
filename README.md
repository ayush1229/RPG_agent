# AI RPG Agent — Multi-Agent Architecture

This project implements a robust, multi-agent RPG chat interface using Chainlit, LangChain, and SQLModel. It relies on three specialized agents with strictly enforced API boundaries to handle narrative orchestration, NPC dialogue generation, and a Tarot-based energy economy.

---

## 1. Agents and Models

The application routes player input through a 3-agent orchestration pipeline. Each agent is driven by a specialized LLM for its unique purpose.

### 🧠 The Game Master (Orchestrator)
- **Model**: `Qwen/Qwen3-Next-80B-A3B-Instruct`
  - *Sampling Settings*: `temperature=0.7`, `top_p=0.8`, `top_k=20`, `min_p=0.0`, `max_tokens=16384`
- **Role**: The frontend-facing orchestrator. It executes in two phases:
  1. **Analysis Phase**: Evaluates the player's action and generates a structured JSON payload (`GMDecision`) to determine if the Persona Agent or Arbiter Agent needs to be invoked.
  2. **Narrative Phase**: Streams the final vivid story response back to the player, incorporating dialogue from the Persona and outcomes from the Arbiter.
- **Constraints**: Read-only access to locations and characters. Can only write narrative events to the `CharacterHistory`. It **cannot** directly mutate the energy economy.
- **Prompts**:
  - *Analysis*: "You are the decision engine of an RPG Game Master. Analyze the player action and return ONLY a valid JSON object..."
  - *Narrative*: "You are an immersive RPG Game Master narrating outcomes vividly... Do NOT invent energy values — use only what is provided in the context."

### 🎭 The Persona Agent (NPC Voice)
- **Model**: `Steelskull/L3.3-Nevoria-R1-70b`
- **Role**: Whenever an NPC speaks, the Game Master delegates dialogue generation to the Persona Agent to ensure character authenticity.
- **Constraints**: 100% read-only. It receives a read-only dictionary of context from the GM and returns purely in-character dialogue.
- **Prompt**: Dynamically built from the NPC's `CharacterPersona` database record: "You are the Persona Agent. You speak exclusively as the character described below... React authentically to the situation given." (Injects Risk Tolerance, Loyalty, and Aggression metrics).

### ⚖️ The Arbiter (Logic & Economy)
- **Model**: `Groq/Llama-3-Groq-8B-Tool-Use`
  - *Sampling Settings*: `temperature=0.5`, `top_p=0.65` (highly sensitive parameters for reliable tool use)
- **Role**: A highly constrained, non-creative rules engine. When the GM realizes an energy/mechanic transfer is required (e.g., combat or intimidation), it asks the Arbiter to resolve it.
- **Constraints**: The Arbiter is the **only** agent permitted to mutate the `TarotEntity` balances. It runs in a custom XML tool-calling loop. It serializes all requests behind an `asyncio.Lock` to prevent race conditions during high concurrency.
- **Prompt**: "You are a function calling AI model... You are the Arbiter — a strict logic and rules engine for an RPG. You may ONLY call tools. Never narrate. Never improvise."

---

## 2. Database Schema (`app/db/models.py`)

The application uses **SQLModel** (built on SQLAlchemy) for its data layer.

### Global & Economy Tables
- **`GlobalConfig`**: Stores hard invariants (e.g., `TOTAL_UPRIGHT_ENERGY` at genesis).
- **`TarotEntity`**: Any entity (player, NPC, the ROOT) that holds Tarot energy. Its `upright_energy` and `reversed_energy` are cached balances. *Never mutated directly.*
- **`TarotTransaction`**: The absolute source of truth. An immutable, append-only ledger of every energy transfer.
- **`TarotShard`**: Represents discrete, named arcana shards (e.g., "The Fool").

### Narrative Tables
- **`Location`**: Physical places in the world. Includes semantic state rules:
  - `is_safe_zone`: The Arbiter will reject any energy transfers that happen here.
  - `is_magic_restricted`: The GM knows to limit magical narrative outcomes here.
- **`SideCharacter`**: Narrative characters linked to a `TarotEntity` wallet, a `Location`, and a `CharacterPersona`.
- **`CharacterHistory`**: An append-only log of roleplay memory. Includes an `event_type` ("dialogue", "combat", "transfer", "movement") to allow agents to selectively recall relevant past events.
- **`CharacterPersona`**: The "NPC Brain." Contains static personality data (`motivation`, `hidden_secret`, `speaking_style`) and numerical behavioral profiles (`risk_tolerance`, `loyalty`, `aggression` on a scale of 0-100) injected directly into the Persona Agent's system prompt.

---

## 3. Core Services (`app/db/service.py`)

### `TarotService`
Handles all atomic interactions with the economy to ensure data integrity and prevent corruption.
- **Conservation Law**: The total amount of energy in the system must remain constant. The service calculates total balances before and after operations to verify this.
- **`mint_energy`**: Used *only* at genesis (bootstrapping the `ROOT` entity).
- **`transfer_energy`**: The core mechanic used by the Arbiter. Atomically debits the sender, credits the receiver, and writes a `TarotTransaction` ledger entry. Uses strict `try/except` blocks with `session.rollback()` to prevent corrupted states on failure.

---

## 4. Inter-Agent Contracts (`app/contracts.py`)

To enforce strict API boundaries, agents communicate via explicit Pydantic schemas:

- **`GMDecision`**: The output of the GM's analysis phase. Determines if `needs_persona` or `needs_arbiter` are true, and provides the `arbiter_instruction`.
- **`PersonaSpeakRequest`**: The context passed from the GM to the Persona Agent (includes the character name, the situation, and recent dialogue history).
- **`EnergyTransferRequest`**: A structured request representing a desired energy movement. (Currently, the GM sends a natural language instruction to the Arbiter, which the Arbiter's LLM translates into tool calls, but this schema structure is available for deeper programmatic integration).
- **`ArbiterResult`**: What the Arbiter returns back to the GM (`success` bool, amounts transferred, and a human-readable `message` for the GM to weave into the final story).
