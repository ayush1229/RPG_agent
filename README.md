# AI RPG Agent — Multi-Agent Architecture

This project implements a Multi-Agent RPG game using Chainlit, LangChain, and SQLModel. It relies on three specialized agents with strictly enforced API boundaries to handle narrative orchestration, NPC dialogue generation, and a Tarot-based energy economy.

---

## 1. Agents and Models

The application routes player input through a 3-agent orchestration pipeline. Each agent is driven by a specialized LLM for its unique purpose.

### 🧠 The Game Master (Orchestrator)
- **Model**: `Qwen/Qwen3-Next-80B-A3B-Instruct`
  - *Sampling Settings*: `temperature=0.7`, `top_p=0.8`, `top_k=20`, `min_p=0.0`, `max_tokens=16384`
- **Role**: The frontend-facing orchestrator. It executes in two phases:
  1. **Analysis Phase**: Evaluates the player's action and generates a structured JSON payload (`GMDecision`) to determine if the Persona Agent or Arbiter Agent needs to be invoked.
  2. **Narrative Phase**: Streams the final vivid story response back to the player, incorporating dialogue from the Persona and outcomes from the Arbiter.
- **Constraints**: Read-only access to locations, characters, and lore. Can only write narrative events to the `CharacterHistory`. It **cannot** directly mutate the energy economy.
- **Prompts**:
  - *Analysis*: "You are the decision engine of an RPG Game Master. Analyze the player action and return ONLY a valid JSON object..." (Injects active scene location, characters, and Tarot Lore dynamically).
  - *Narrative*: "You are an immersive RPG Game Master narrating outcomes vividly... Do NOT invent energy values — use only what is provided in the context. When a character uses magic, strictly align their abilities with their Tarot Magic Style."

### 🎭 The Persona Agent (NPC Voice)
- **Model**: `Steelskull/L3.3-Nevoria-R1-70b`
- **Role**: Whenever an NPC speaks, the Game Master delegates dialogue generation to the Persona Agent to ensure character authenticity.
- **Constraints**: 100% read-only. It receives a read-only dictionary of context from the GM and returns purely in-character dialogue.
- **Prompt**: Dynamically built from the NPC's `CharacterPersona` database record: "You are the Persona Agent. You speak exclusively as the character described below... React authentically to the situation given." (Injects Risk Tolerance, Loyalty, Aggression metrics, and their Tarot Affinity lore block).

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
- **`GlobalConfig`**: Stores hard invariants (e.g., `TOTAL_UPRIGHT_CAPACITY` at genesis).
- **`TarotEntity`**: Any entity (player, NPC, the ROOT) that holds Tarot energy. It implements a **Dual-Layer Economy**:
  - **Capacity**: Permanent, zero-sum energy determining sovereignty.
  - **Mana**: Spendable energy for spell casting. Regenerates lazily at 1 unit per minute.
- **`TarotTransaction`**: The absolute source of truth. An immutable, append-only ledger of every capacity transfer.
- **`TarotCardTransaction`**: Immutable ledger of Tarot card ownership transfers.
- **`TarotShard`**: Represents discrete arcana shards, linked via foreign key directly to the `TarotCardLore` that names and defines them. Enforces a strict loadout of 1 Major and 2 Minor Arcana per entity.
- **`TarotAbility`**: Spells or actions unlocked by holding specific Tarot cards. Includes strict categorical rules (`combat`, `utility`, `passive`) and structured parsing tags.

### Static Lore (Reference Data)
- **`TarotCardLore`**: Static reference table for Tarot meanings and magical themes. The database is fully seeded with all 78 Tarot Cards (22 Major, 56 Minor including Court cards) and 30 integrated abilities.

### Narrative Tables
- **`Location`**: Physical places in the world. Includes semantic state rules:
  - `is_safe_zone`: The Arbiter will reject any energy transfers that happen here.
  - `is_magic_restricted`: The GM knows to limit magical narrative outcomes here.
- **`SideCharacter`**: Narrative characters linked to a `TarotEntity` wallet, a `Location`, and a `CharacterPersona`.
- **`CharacterHistory`**: An append-only log of roleplay memory. Includes an `event_type` ("dialogue", "combat", "transfer", "movement") to allow agents to selectively recall relevant past events.
- **`CharacterPersona`**: The "NPC Brain." Contains static personality data (`motivation`, `hidden_secret`, `speaking_style`), numerical behavioral profiles (`risk_tolerance`, `loyalty`, `aggression`), and a relationship to `TarotCardLore` that dictates their magic style.

---

## 3. Core Services

### `TarotService` (`app/db/service.py`)
Handles all atomic interactions with the economy to ensure data integrity and prevent corruption.
- **Conservation Law**: Capacity is strictly conserved.
- **Lazy Mana Regeneration**: Mana regenerates automatically (1 unit per minute) calculated instantly upon access, requiring no background loops.
- **`transfer_energy`**: Atomically debits the sender, credits the receiver, and writes a ledger entry. Uses strict `try/except` blocks with `session.rollback()` to prevent corrupted states.
- **`transfer_card`**: Handles transferring Tarot Shards, strictly enforcing the 1 Major / 2 Minor loadout limits.
- **`cast_spell`**: Validates card ownership, applies lazy mana regeneration, and deducts the correct energy type cost for spell casting.

### JIT Context Builder (`app/db/context.py`)
Prevents token-limit exhaustion by dynamically assembling context strings only for the active scene.
- **`build_gm_context`**: Assembles location details, current occupants, and active Tarot lore into a single string injected into the GM's prompts.
- **`get_character_lore_block`**: Fetches a single character's archetype ("Your soul is bound to the archetype of...") to inject directly into the Persona Agent's prompt.

---

## 4. Inter-Agent Contracts (`app/contracts.py`)

To enforce strict API boundaries, agents communicate via explicit Pydantic schemas:

- **`GMDecision`**: The output of the GM's analysis phase. Determines if `needs_persona` or `needs_arbiter` are true, and provides the `arbiter_instruction`.
- **`PersonaSpeakRequest`**: The context passed from the GM to the Persona Agent (includes the character name, the situation, and recent dialogue history).
- **`EnergyTransferRequest`**: A structured request representing a desired energy movement. (Currently, the GM sends a natural language instruction to the Arbiter, which the Arbiter's LLM translates into tool calls, but this schema structure is available for deeper programmatic integration).
- **`ArbiterResult`**: What the Arbiter returns back to the GM (`success` bool, amounts transferred, and a human-readable `message` for the GM to weave into the final story).

### `GameState` (Execution Flow)
The engine strictly orchestrates interactions through a deterministic state machine to prevent hallucination and double-narration:
1. **ACTIVE_ROLEPLAY**: Default state for exploration and GM narration.
2. **NPC_INTERACTION**: Clean hand-off to the Persona Agent for character dialogue.
3. **SYSTEM_INTERCEPT**: GM pauses when a mechanic or conflict is detected.
4. **ARBITER_RESOLUTION**: Arbiter executes the strict rules and state mutations.
5. **POST_RESOLUTION**: GM translates the Arbiter's outcomes back into narrative format.

---

## 5. Testing

The core rules engine and service layer are backed by a comprehensive `pytest` suite testing all atomic operations, ensuring high reliability for:
- Lazy Mana Regeneration logic
- Atomic Energy and Card Transfers
- Loadout Limit Enforcement
- Spell Casting and Resource Deduction
