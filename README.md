# AI RPG Agent — Multi-Agent Architecture

This project implements a Multi-Agent RPG game using Chainlit, LangChain, and SQLModel. It relies on three specialized agents with strictly enforced API boundaries to handle narrative orchestration, NPC dialogue generation, and a Tarot-based energy economy.

---

## 1. Agents and Models

The application routes player input through a 3-agent orchestration pipeline. Each agent is driven by a specialized LLM for its unique purpose.

### 🧠 The Game Master (Orchestrator)
- **Model**: `Qwen/Qwen3-Next-80B-A3B-Instruct`
- **Role**: The frontend-facing orchestrator. Executes in two phases:
  1. **Analysis Phase**: Evaluates player action to generate a structured `GMDecision`, determining if the Persona Agent or Arbiter Agent is needed.
  2. **Narrative Phase**: Streams the final vivid story response back to the player, incorporating Persona dialogue and Arbiter outcomes.
- **Constraints**: Read-only access to world state. Subject to Narrative Control (`StoryEnforcer`), which can bypass the GM entirely for mandatory story beats.

### 🎭 The Persona Agent (NPC Voice)
- **Model**: `Steelskull/L3.3-Nevoria-R1-70b`
- **Role**: Generates authentic, in-character NPC dialogue.
- **Constraints**: 100% read-only. Driven by `CharacterPersona` records (Motivation, Secret, Speaking Style, Risk Tolerance, Loyalty, Aggression, and Tarot Affinity).

### ⚖️ The Arbiter (Logic & Economy)
- **Model**: `Groq/Llama-3-Groq-8B-Tool-Use`
- **Role**: A highly constrained, non-creative rules engine that acts via Tool Calls.
- **Constraints**: The Arbiter is the **only** agent permitted to mutate `TarotEntity` balances. Serializes all requests behind an `asyncio.Lock` to prevent race conditions.

---

## 2. World Systems & Persistence

The application uses **SQLModel** (built on SQLAlchemy) for its data layer.

### Narrative Control & Persistence
- **`UserSession` & `DialogueLog`**: Replaces transient in-memory chat history. Fully persists player states across restarts.
- **`ConversationSummary`**: Uses an LLM summarizer to compress long-term chat history into key facts, injecting them into the context window rather than raw logs to save tokens.
- **`MainStoryState` (Story Enforcer)**: Tracks canonical main quest progression across 7 Arcs. Enforces mandatory gates (e.g. Prologue Interview → Card Draw → Awakening) by completely bypassing the GM until completed.

### The World Map & Travel
- **`WorldMap` & `Location`**: 10 Major Kingdoms (with rulers and legendary items) and 15 Minor Kingdoms. Includes spatial coordinates (`x`, `y`).
- **`TravelState`**: Movement is not instant. Travel time is calculated dynamically based on distance, entity speed, and `TERRAIN_MODIFIERS`. Runs asynchronously using a lazy-tick system.

### Factions, Wars, & Sovereign Influence
- **`Faction` & `TerritoryControl`**: Kingdoms fight for control. Faction relations scale from -100 (war) to +100 (allied).
- **`War`**: Active wars slowly drain and shift territorial control.
- **`SovereignInfluence`**: Entities holding >50% of a Major Arcana pool exert influence. If influence exceeds 70%, the location becomes highly unstable, altering spawn rates and danger levels.
- **`WorldEvent`**: Time-limited events (wars, anomalies, festivals, sieges) that apply dynamic multipliers to the world.

### Global & Economy Tables
- **`TarotEntity`**: Any entity (player, NPC, the ROOT). Includes health, mana, level, and XP progression.
- **`TarotTransaction`**: Immutable ledger of all energy capacity transfers.
- **`InventoryItem` & `Quest`**: Items feature rarities and trade values. Quests reward XP scaled by player level and difficulty.

---

## 3. Core Services

### `WorldService` (`app/db/world_service.py`)
Features a lazy-tick architecture: `process_world_delta` is called at the start of every player interaction to catch up the simulation. Resolves active travel journeys, shifts territory control during wars, spreads sovereign influence, and decays event timers.

### `SessionService` (`app/db/session_service.py`)
Handles persistent rehydration. Limits context injection to the last N messages plus the `ConversationSummary` to ensure maximum token efficiency.

### `TarotService` (`app/db/service.py`)
Handles all atomic interactions with the economy:
- **Conservation Law**: Capacity is strictly conserved.
- **Lazy Mana Regeneration**: Mana regenerates automatically (1 unit per minute) calculated instantly upon access.
- **`transfer_energy`**: Atomically debits and credits energy using strict rollbacks to prevent corruption.

---

## 4. Execution Flow (Message Pipeline)

Every message follows a strict pipeline to prevent hallucination and double-narration:
1. `save_dialogue`: Persist user message.
2. `load_user_state`: Rehydrate player DB state.
3. `build_agent_context`: Build minimal LLM context.
4. **Story Enforcer Check**: If a mandatory story gate is hit, skip GM and return forced narrative.
5. `GM.analyze`: Output a structured `GMDecision`.
6. `PersonaAgent` / `ArbiterAgent`: Execute specialized tasks if required.
7. `GM.narrate`: Stream the final story back to the user.
8. `update_user_session`: Save new location, quests, and game state.
9. `maybe_update_summary`: Trigger LLM history compression every N messages.

---

## 5. Testing

The core rules engine, service layer, and world simulation are backed by a massive 250+ test `pytest` suite ensuring high reliability for:
- Lazy-tick World Simulation (Travel, Wars, Events)
- Story Enforcer Progression Gates
- Persistent Session & Chat Summarization
- Atomic Energy and Card Transfers
- Spell Casting and Resource Deduction
