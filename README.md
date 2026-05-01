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
- **Constraints**: Read-only access to world state. Subject to Narrative Control (`StoryEnforcer` and `TutorialEnforcer`), which can inject mandatory context or `is_gm_directive` system overrides to force specific scene beats without exposing raw instructions to the player.
- **Logging**: All prompts, history, context, and generated narrative tokens are captured by the `SessionLLMLogger` and saved per-session in the `logs/` directory.

### 🎭 The Persona Agent (NPC Voice)
- **Model**: `Steelskull/L3.3-Nevoria-R1-70b`
- **Role**: Generates authentic, in-character NPC dialogue.
- **Constraints**: 100% read-only. Driven by `SideCharacter` records with personality, status, and Tarot affinity hints.

### ⚖️ The Arbiter (Logic & Economy)
- **Model**: `Groq/Llama-3-Groq-8B-Tool-Use`
- **Role**: A highly constrained, non-creative rules engine that acts via Tool Calls.
- **Constraints**: The Arbiter is the **only** agent permitted to mutate `TarotEntity` balances. Serializes all requests behind an `asyncio.Lock` to prevent race conditions.

---

## 2. World Systems & Persistence

The application uses **SQLModel** (built on SQLAlchemy) for its data layer.

### Narrative Control, Persistence & Isolation
- **`UserSession` & `DialogueLog`**: Fully persists player states across restarts. Includes `chat_session_id` to isolate message windows per browser tab.
- **Custom Chainlit Data Layer**: `app/chainlit_data_layer.py` exposes the `DialogueLog` table to Chainlit's UI. This provides a persistent **Thread History Sidebar**, allowing players to view past chat sessions and seamlessly resume them exactly where they left off. 
- **Silent Authentication**: Uses `@cl.header_auth_callback` to silently authenticate all visitors as a unified player profile, bypassing login forms while still grouping sessions.
- **`ConversationSummary`**: Uses an LLM summarizer to compress long-term, cross-session chat history into key facts, injected into the context window to save tokens.
- **`TutorialEnforcer` (Elaris Hollow)**: An 11-phase controlled onboarding pipeline disguised as narrative. Gates mechanics (combat, economy, housing) progressively.
- **`StoryEnforcer` (MainStoryState)**: Tracks canonical main quest progression across 7 Arcs. Enforces mandatory gates (e.g., Prologue Interview).

### Global Time, Housing, & Dreamscape
- **`WorldTime`**: A lazy-tick deterministic global clock scaling real-world seconds into game time. Drives the Day/Night cycle (`NIGHT_RISK_MULTIPLIER` = 1.7x risk/difficulty at night).
- **Housing System**: Players can rent or buy housing to establish safe zones, completely nullifying night risk multipliers when sheltered.
- **Dreamscape**: A magic-restricted alternative realm gated behind probabilistic entry (requires night time, out-of-combat, and story unlocks) with narrative flag persistence.

### The World Map, Events, & Travel
- **`WorldMap` & `Location`**: Includes spatial coordinates (`x`, `y`).
- **`TravelState`**: Movement travel time calculated dynamically based on distance, entity speed, and `TERRAIN_MODIFIERS`.
- **`WorldEventInstance`**: Spawns dynamic, time-bound side quests/anomalies (probabilistic selection via `EventTemplate`). Weighted by location modifiers (wars, sovereign influence, day/night).

### Factions, Wars, & Sovereign Influence
- **`Faction` & `TerritoryControl`**: Factions battle for control via the `War` system.
- **`SovereignInfluence`**: Entities holding >50% of a Major Arcana pool exert influence, destabilizing locations.
- **`Guild` & Dual-Membership**: Players can join specialized guilds (e.g., combat, magic, shadow) and gain reputation, gaining access to guild-specific quests and headquarters.

### Global & Economy Tables
- **`TarotEntity`**: Any entity (player, NPC, the ROOT). Includes health, mana, level, and XP progression.
- **`TarotTransaction`**: Immutable ledger of all energy capacity transfers.
- **`Wallet` & Economy System**: Full gold-based currency, shops, dynamic item pricing, auctions, and tradable items.
- **`Quest` & `InventoryItem`**: Quests reward scaled XP and items. Items have durability, value, and stackability.

---

## 3. Core Services

### `WorldService` (`app/db/world_service.py`)
Features a lazy-tick architecture: `process_world_delta` is called at the start of every player interaction to catch up the simulation. Resolves active travel journeys, shifts territory control during wars, spreads sovereign influence, and decays event timers.

### `TimeService` & `TutorialService`
`update_time` is called automatically at the top of the LLM pipeline, advancing the global clock and synchronizing expiry/cooldowns. `build_tutorial_context` injects phase-specific, purely narrative instructions into the GM's prompt.

### `SessionService` & `LLMLogger`
`app/db/session_service.py` handles persistent rehydration and per-tab isolation. Limits context injection to the last N messages of the *current* chat tab plus the cross-session `ConversationSummary`. `app/llm_logger.py` acts as a LangChain callback handler, saving the exact LLM prompt and output into `logs/<session_id>.log` for debugging and transparency.

### `TarotService` (`app/db/service.py`)
Handles all atomic interactions with the energy economy:
- **Conservation Law**: Capacity is strictly conserved.
- **Lazy Mana Regeneration**: Regens automatically upon access.

---

## 4. Execution Flow (Message Pipeline)

Every message follows a strict pipeline to prevent hallucination and double-narration:
1. `save_dialogue`: Persist user message (scoped by `chat_session_id`).
2. `load_user_state`: Rehydrate player DB state and this tab's recent messages.
3. `build_agent_context`: Build minimal LLM context.
4. **Story/Tutorial Enforcer Checks**: Advance phases, inject constraints, or bypass the GM completely with forced narrative.
5. `GM.analyze`: Output a structured `GMDecision`.
6. `PersonaAgent` / `ArbiterAgent`: Execute specialized tasks if required.
7. `GM.narrate`: Stream the final story back to the user.
8. `update_user_session`: Save new location, quests, and game state.
9. `maybe_update_summary`: Trigger LLM history compression every N messages.

---

## 5. Testing

The core rules engine, service layer, and world simulation are backed by a massive 570+ test `pytest` suite ensuring high reliability for:
- Lazy-tick World Simulation (Travel, Wars, Events, Time)
- Tutorial Gating & Story Enforcer Progression
- Persistent Session, Tab Isolation, & Chat Summarization
- Atomic Energy, Gold, and Item Transfers
- Combat Engine & Spell Casting
- Guilds, Economy, Housing, & Dreamscape Logic
