"""
seed.py — Genesis script for the AI RPG Tarot System.

Run once to:
  1. Create all DB tables
  2. Write GlobalConfig capacity constants
  3. Create the ROOT (WORLD_CORE) entity
  4. Seed all 22 Major Arcana into TarotCardLore

Usage:
    uv run python seed.py
"""
from __future__ import annotations

from app.db.database import create_db_and_tables, get_session, init_root
from app.db.models import TarotCardLore, TarotAbility
from sqlmodel import select

# ─── 22 Major Arcana ─────────────────────────────────────────────────────────
MAJOR_ARCANA: list[dict] = [
    {
        "name": "The Fool",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Beginnings, risk, innocence",
        "reversed_meaning": "Recklessness, poor decisions, naivety",
        "magical_manifestation": "Unpredictable movement, chaos magic, spatial distortion",
        "personality_archetype": "Reckless, curious, fearless explorer",
        "core_themes": "beginnings, chaos, freedom",
        "power_domains": "movement, probability, instability",
        "behavioral_bias": "impulsive, optimistic, unaware of danger"
    },
    {
        "name": "The Magician",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Action, manifestation, creativity",
        "reversed_meaning": "Manipulation, deception, misuse of power",
        "magical_manifestation": "Elemental control, spellcasting, energy manipulation",
        "personality_archetype": "Confident creator, manipulator of reality",
        "core_themes": "creation, willpower, control",
        "power_domains": "elements, transformation, energy shaping",
        "behavioral_bias": "strategic, confident, controlling"
    },
    {
        "name": "The High Priestess",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Intuition, secrets, hidden knowledge",
        "reversed_meaning": "Confusion, blocked intuition, secrecy",
        "magical_manifestation": "Illusions, foresight, psychic influence",
        "personality_archetype": "Silent observer, keeper of secrets",
        "core_themes": "mystery, intuition, hidden truth",
        "power_domains": "mind, perception, illusion",
        "behavioral_bias": "reserved, observant, enigmatic"
    },
    {
        "name": "The Empress",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Creation, nurturing, abundance",
        "reversed_meaning": "Dependence, stagnation, neglect",
        "magical_manifestation": "Life magic, growth acceleration, healing",
        "personality_archetype": "Nurturer, creator, protector",
        "core_themes": "growth, life, abundance",
        "power_domains": "nature, fertility, healing",
        "behavioral_bias": "caring, protective, generous"
    },
    {
        "name": "The Emperor",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Order, authority, structure",
        "reversed_meaning": "Tyranny, rigidity, control issues",
        "magical_manifestation": "Barrier creation, command magic, control fields",
        "personality_archetype": "Ruler, strategist, authority figure",
        "core_themes": "order, power, control",
        "power_domains": "structure, command, defense",
        "behavioral_bias": "dominant, disciplined, controlling"
    },
    {
        "name": "The Hierophant",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Tradition, knowledge, guidance",
        "reversed_meaning": "Rebellion, dogma, restriction",
        "magical_manifestation": "Ritual magic, divine blessings, knowledge transfer",
        "personality_archetype": "Teacher, priest, guide",
        "core_themes": "tradition, wisdom, structure",
        "power_domains": "rituals, knowledge, faith",
        "behavioral_bias": "conservative, guiding, structured"
    },
    {
        "name": "The Lovers",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Love, union, choice",
        "reversed_meaning": "Conflict, imbalance, broken trust",
        "magical_manifestation": "Bond magic, soul linking, emotional amplification",
        "personality_archetype": "Connector, emotional decision-maker",
        "core_themes": "connection, choice, duality",
        "power_domains": "relationships, bonds, emotion",
        "behavioral_bias": "empathetic, indecisive, passionate"
    },
    {
        "name": "The Chariot",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Determination, control, victory",
        "reversed_meaning": "Loss of control, aggression, failure",
        "magical_manifestation": "Momentum control, speed enhancement, force projection",
        "personality_archetype": "Warrior, conqueror",
        "core_themes": "willpower, victory, movement",
        "power_domains": "motion, force, direction",
        "behavioral_bias": "driven, aggressive, focused"
    },
    {
        "name": "Strength",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Endurance, courage, inner power",
        "reversed_meaning": "Weakness, doubt, insecurity",
        "magical_manifestation": "Enhancement magic, resilience boosts, inner aura",
        "personality_archetype": "Calm warrior, inner strength",
        "core_themes": "courage, resilience, patience",
        "power_domains": "body, endurance, will",
        "behavioral_bias": "calm, determined, controlled"
    },
    {
        "name": "The Hermit",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Solitude, wisdom, introspection",
        "reversed_meaning": "Isolation, loneliness, avoidance",
        "magical_manifestation": "Stealth, concealment, knowledge aura",
        "personality_archetype": "Seeker, isolated sage",
        "core_themes": "reflection, solitude, wisdom",
        "power_domains": "knowledge, concealment, awareness",
        "behavioral_bias": "withdrawn, thoughtful, distant"
    },
    {
        "name": "The Wheel of Fortune",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Fate, luck, cycles",
        "reversed_meaning": "Misfortune, stagnation, bad luck",
        "magical_manifestation": "Probability manipulation, fate bending",
        "personality_archetype": "Agent of change",
        "core_themes": "luck, cycles, change",
        "power_domains": "probability, time, randomness",
        "behavioral_bias": "adaptive, unpredictable"
    },
    {
        "name": "Justice",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Balance, truth, law",
        "reversed_meaning": "Injustice, bias, imbalance",
        "magical_manifestation": "Judgment magic, truth enforcement",
        "personality_archetype": "Judge, arbiter",
        "core_themes": "balance, truth, fairness",
        "power_domains": "law, equilibrium, consequence",
        "behavioral_bias": "logical, fair, strict"
    },
    {
        "name": "The Hanged Man",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Waiting, sacrifice, letting go, new perspective",
        "reversed_meaning": "Stalling, resistance, indecision, unnecessary sacrifice",
        "magical_manifestation": "Time suspension, gravity inversion, stasis fields",
        "personality_archetype": "Detached observer, self-sacrificing visionary",
        "core_themes": "sacrifice, perspective, surrender",
        "power_domains": "time, suspension, perception",
        "behavioral_bias": "passive, contemplative, accepting"
    },
    {
        "name": "Death",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Transformation, endings, rebirth",
        "reversed_meaning": "Stagnation, resistance to change",
        "magical_manifestation": "Decay, rebirth cycles, transformation",
        "personality_archetype": "Harbinger of change",
        "core_themes": "endings, rebirth, transformation",
        "power_domains": "life cycle, decay, renewal",
        "behavioral_bias": "detached, inevitable"
    },
    {
        "name": "Temperance",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Balance, moderation, harmony, integration",
        "reversed_meaning": "Imbalance, excess, discord, lack of alignment",
        "magical_manifestation": "Energy blending, elemental fusion, equilibrium fields",
        "personality_archetype": "Harmonizer, mediator, alchemist",
        "core_themes": "balance, harmony, synthesis",
        "power_domains": "fusion, equilibrium, flow",
        "behavioral_bias": "calm, patient, adaptive"
    },
    {
        "name": "The Devil",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Bondage, temptation, control",
        "reversed_meaning": "Freedom, release, awakening",
        "magical_manifestation": "Chains, corruption, domination magic",
        "personality_archetype": "Manipulator, corrupter",
        "core_themes": "control, desire, bondage",
        "power_domains": "control, corruption, influence",
        "behavioral_bias": "tempting, controlling, cunning"
    },
    {
        "name": "The Tower",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Destruction, sudden change, revelation",
        "reversed_meaning": "Avoided disaster, fear of change",
        "magical_manifestation": "Explosive magic, destruction waves",
        "personality_archetype": "Agent of chaos",
        "core_themes": "destruction, chaos, revelation",
        "power_domains": "explosion, disruption, shock",
        "behavioral_bias": "volatile, disruptive"
    },
    {
        "name": "The Star",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Hope, guidance, healing",
        "reversed_meaning": "Despair, lack of faith",
        "magical_manifestation": "Healing light, guidance beams",
        "personality_archetype": "Hope bringer",
        "core_themes": "hope, guidance, renewal",
        "power_domains": "light, healing, direction",
        "behavioral_bias": "calm, optimistic"
    },
    {
        "name": "The Moon",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Illusion, fear, subconscious",
        "reversed_meaning": "Clarity, truth revealed",
        "magical_manifestation": "Dream magic, illusion fields",
        "personality_archetype": "Mystic, illusionist",
        "core_themes": "illusion, fear, mystery",
        "power_domains": "mind, dreams, deception",
        "behavioral_bias": "uncertain, deceptive"
    },
    {
        "name": "The Sun",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Success, vitality, joy",
        "reversed_meaning": "Temporary setbacks, overconfidence",
        "magical_manifestation": "Radiant energy, life force bursts",
        "personality_archetype": "Radiant leader",
        "core_themes": "success, vitality, clarity",
        "power_domains": "light, energy, life",
        "behavioral_bias": "confident, energetic"
    },
    {
        "name": "Judgment",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Rebirth, awakening, evaluation",
        "reversed_meaning": "Self-doubt, avoidance",
        "magical_manifestation": "Revival, soul awakening",
        "personality_archetype": "Redeemer",
        "core_themes": "rebirth, judgment, awakening",
        "power_domains": "soul, resurrection, clarity",
        "behavioral_bias": "reflective, decisive"
    },
    {
        "name": "The World",
        "arcana_type": "Major",
        "suit": None,
        "upright_meaning": "Completion, success, fulfillment",
        "reversed_meaning": "Incomplete, delay",
        "magical_manifestation": "Reality stabilization, completion magic",
        "personality_archetype": "Master of cycles",
        "core_themes": "completion, unity, success",
        "power_domains": "space, balance, totality",
        "behavioral_bias": "balanced, fulfilled"
    },
]

# ─── 56 Minor Arcana ─────────────────────────────────────────────────────────
MINOR_ARCANA: list[dict] = [
  {"name":"Ace of Cups","arcana_type":"Minor","suit":"Cups","upright_meaning":"New emotions, love, intuition","reversed_meaning":"Emotional block, emptiness","magical_manifestation":"Healing aura, emotional surge","personality_archetype":"Empathic initiator","core_themes":"emotion, beginnings","power_domains":"healing, water, emotion","behavioral_bias":"open, sensitive"},
  {"name":"Two of Cups","arcana_type":"Minor","suit":"Cups","upright_meaning":"Union, partnership","reversed_meaning":"Separation, imbalance","magical_manifestation":"Bond linking, shared energy","personality_archetype":"Connector","core_themes":"union, balance","power_domains":"links, emotion","behavioral_bias":"cooperative"},
  {"name":"Three of Cups","arcana_type":"Minor","suit":"Cups","upright_meaning":"Celebration, friendship","reversed_meaning":"Overindulgence, conflict","magical_manifestation":"Morale boost, group resonance","personality_archetype":"Social celebrant","core_themes":"joy, community","power_domains":"support, emotion","behavioral_bias":"cheerful"},
  {"name":"Four of Cups","arcana_type":"Minor","suit":"Cups","upright_meaning":"Apathy, contemplation","reversed_meaning":"Awareness, acceptance","magical_manifestation":"Emotional dampening","personality_archetype":"Detached thinker","core_themes":"reflection, stagnation","power_domains":"mind, emotion","behavioral_bias":"withdrawn"},
  {"name":"Five of Cups","arcana_type":"Minor","suit":"Cups","upright_meaning":"Loss, regret","reversed_meaning":"Recovery, forgiveness","magical_manifestation":"Grief aura, emotional drain","personality_archetype":"Mourner","core_themes":"loss, recovery","power_domains":"emotion, decay","behavioral_bias":"melancholic"},
  {"name":"Six of Cups","arcana_type":"Minor","suit":"Cups","upright_meaning":"Nostalgia, memory","reversed_meaning":"Stuck in past","magical_manifestation":"Memory projection","personality_archetype":"Dreamer","core_themes":"past, innocence","power_domains":"memory, illusion","behavioral_bias":"sentimental"},
  {"name":"Seven of Cups","arcana_type":"Minor","suit":"Cups","upright_meaning":"Choices, illusion","reversed_meaning":"Clarity, focus","magical_manifestation":"Illusion fields","personality_archetype":"Visionary","core_themes":"illusion, choice","power_domains":"illusion, mind","behavioral_bias":"indecisive"},
  {"name":"Eight of Cups","arcana_type":"Minor","suit":"Cups","upright_meaning":"Withdrawal, journey","reversed_meaning":"Avoidance","magical_manifestation":"Phase shift, retreat magic","personality_archetype":"Seeker","core_themes":"departure, search","power_domains":"movement, emotion","behavioral_bias":"detached"},
  {"name":"Nine of Cups","arcana_type":"Minor","suit":"Cups","upright_meaning":"Satisfaction, wish fulfillment","reversed_meaning":"Greed, dissatisfaction","magical_manifestation":"Desire manifestation","personality_archetype":"Satisfied achiever","core_themes":"fulfillment","power_domains":"desire, emotion","behavioral_bias":"content"},
  {"name":"Ten of Cups","arcana_type":"Minor","suit":"Cups","upright_meaning":"Harmony, happiness","reversed_meaning":"Broken harmony","magical_manifestation":"Harmony field","personality_archetype":"Harmonizer","core_themes":"unity, joy","power_domains":"balance, emotion","behavioral_bias":"peaceful"},

  {"name":"Ace of Swords","arcana_type":"Minor","suit":"Swords","upright_meaning":"Clarity, truth","reversed_meaning":"Confusion","magical_manifestation":"Energy blade, truth strike","personality_archetype":"Truth seeker","core_themes":"clarity","power_domains":"mind, air","behavioral_bias":"direct"},
  {"name":"Two of Swords","arcana_type":"Minor","suit":"Swords","upright_meaning":"Indecision","reversed_meaning":"Decision","magical_manifestation":"Barrier shield","personality_archetype":"Balancer","core_themes":"choice","power_domains":"defense, mind","behavioral_bias":"neutral"},
  {"name":"Three of Swords","arcana_type":"Minor","suit":"Swords","upright_meaning":"Heartbreak","reversed_meaning":"Recovery","magical_manifestation":"Pain spike","personality_archetype":"Sufferer","core_themes":"pain","power_domains":"emotion, damage","behavioral_bias":"hurt"},
  {"name":"Four of Swords","arcana_type":"Minor","suit":"Swords","upright_meaning":"Rest, recovery","reversed_meaning":"Burnout","magical_manifestation":"Stasis rest field","personality_archetype":"Recoverer","core_themes":"rest","power_domains":"healing, mind","behavioral_bias":"calm"},
  {"name":"Five of Swords","arcana_type":"Minor","suit":"Swords","upright_meaning":"Conflict, defeat","reversed_meaning":"Reconciliation","magical_manifestation":"Disruption wave","personality_archetype":"Opportunist","core_themes":"conflict","power_domains":"combat, disruption","behavioral_bias":"selfish"},
  {"name":"Six of Swords","arcana_type":"Minor","suit":"Swords","upright_meaning":"Transition","reversed_meaning":"Stagnation","magical_manifestation":"Teleport glide","personality_archetype":"Traveler","core_themes":"transition","power_domains":"movement, air","behavioral_bias":"adaptable"},
  {"name":"Seven of Swords","arcana_type":"Minor","suit":"Swords","upright_meaning":"Deception","reversed_meaning":"Truth revealed","magical_manifestation":"Stealth cloak","personality_archetype":"Trickster","core_themes":"deception","power_domains":"stealth, mind","behavioral_bias":"sly"},
  {"name":"Eight of Swords","arcana_type":"Minor","suit":"Swords","upright_meaning":"Restriction","reversed_meaning":"Freedom","magical_manifestation":"Binding field","personality_archetype":"Prisoner","core_themes":"limitation","power_domains":"control, mind","behavioral_bias":"trapped"},
  {"name":"Nine of Swords","arcana_type":"Minor","suit":"Swords","upright_meaning":"Anxiety","reversed_meaning":"Release","magical_manifestation":"Fear aura","personality_archetype":"Worrier","core_themes":"fear","power_domains":"mind, illusion","behavioral_bias":"anxious"},
  {"name":"Ten of Swords","arcana_type":"Minor","suit":"Swords","upright_meaning":"Endings","reversed_meaning":"Recovery","magical_manifestation":"Final strike","personality_archetype":"Fallen one","core_themes":"ending","power_domains":"destruction","behavioral_bias":"defeated"},

  {"name":"Ace of Wands","arcana_type":"Minor","suit":"Wands","upright_meaning":"Inspiration","reversed_meaning":"Delay","magical_manifestation":"Fire ignition","personality_archetype":"Initiator","core_themes":"energy","power_domains":"fire, creation","behavioral_bias":"driven"},
  {"name":"Two of Wands","arcana_type":"Minor","suit":"Wands","upright_meaning":"Planning","reversed_meaning":"Fear of change","magical_manifestation":"Vision projection","personality_archetype":"Planner","core_themes":"planning","power_domains":"future, fire","behavioral_bias":"strategic"},
  {"name":"Three of Wands","arcana_type":"Minor","suit":"Wands","upright_meaning":"Expansion","reversed_meaning":"Delay","magical_manifestation":"Range extension","personality_archetype":"Explorer","core_themes":"growth","power_domains":"expansion","behavioral_bias":"optimistic"},
  {"name":"Four of Wands","arcana_type":"Minor","suit":"Wands","upright_meaning":"Stability","reversed_meaning":"Instability","magical_manifestation":"Protective field","personality_archetype":"Builder","core_themes":"foundation","power_domains":"structure","behavioral_bias":"stable"},
  {"name":"Five of Wands","arcana_type":"Minor","suit":"Wands","upright_meaning":"Competition","reversed_meaning":"Avoid conflict","magical_manifestation":"Chaos sparks","personality_archetype":"Competitor","core_themes":"conflict","power_domains":"fire, clash","behavioral_bias":"aggressive"},
  {"name":"Six of Wands","arcana_type":"Minor","suit":"Wands","upright_meaning":"Victory","reversed_meaning":"Ego","magical_manifestation":"Aura boost","personality_archetype":"Champion","core_themes":"success","power_domains":"confidence","behavioral_bias":"proud"},
  {"name":"Seven of Wands","arcana_type":"Minor","suit":"Wands","upright_meaning":"Defense","reversed_meaning":"Overwhelmed","magical_manifestation":"Barrier stance","personality_archetype":"Defender","core_themes":"defense","power_domains":"protection","behavioral_bias":"resilient"},
  {"name":"Eight of Wands","arcana_type":"Minor","suit":"Wands","upright_meaning":"Speed","reversed_meaning":"Delay","magical_manifestation":"Rapid projectiles","personality_archetype":"Messenger","core_themes":"speed","power_domains":"motion","behavioral_bias":"fast-paced"},
  {"name":"Nine of Wands","arcana_type":"Minor","suit":"Wands","upright_meaning":"Persistence","reversed_meaning":"Exhaustion","magical_manifestation":"Endurance aura","personality_archetype":"Survivor","core_themes":"resilience","power_domains":"stamina","behavioral_bias":"defensive"},
  {"name":"Ten of Wands","arcana_type":"Minor","suit":"Wands","upright_meaning":"Burden","reversed_meaning":"Release","magical_manifestation":"Weight manipulation","personality_archetype":"Burdened","core_themes":"pressure","power_domains":"gravity","behavioral_bias":"overworked"},

  {"name":"Ace of Pentacles","arcana_type":"Minor","suit":"Pentacles","upright_meaning":"Opportunity","reversed_meaning":"Lost chance","magical_manifestation":"Material creation","personality_archetype":"Builder","core_themes":"growth","power_domains":"earth, wealth","behavioral_bias":"practical"},
  {"name":"Two of Pentacles","arcana_type":"Minor","suit":"Pentacles","upright_meaning":"Balance","reversed_meaning":"Imbalance","magical_manifestation":"Energy balancing","personality_archetype":"Juggler","core_themes":"balance","power_domains":"flow","behavioral_bias":"adaptive"},
  {"name":"Three of Pentacles","arcana_type":"Minor","suit":"Pentacles","upright_meaning":"Teamwork","reversed_meaning":"Lack of cooperation","magical_manifestation":"Skill amplification","personality_archetype":"Craftsman","core_themes":"collaboration","power_domains":"skill","behavioral_bias":"cooperative"},
  {"name":"Four of Pentacles","arcana_type":"Minor","suit":"Pentacles","upright_meaning":"Control","reversed_meaning":"Greed","magical_manifestation":"Resource locking","personality_archetype":"Guardian","core_themes":"control","power_domains":"earth, defense","behavioral_bias":"possessive"},
  {"name":"Five of Pentacles","arcana_type":"Minor","suit":"Pentacles","upright_meaning":"Hardship","reversed_meaning":"Recovery","magical_manifestation":"Drain aura","personality_archetype":"Struggler","core_themes":"lack","power_domains":"decay","behavioral_bias":"desperate"},
  {"name":"Six of Pentacles","arcana_type":"Minor","suit":"Pentacles","upright_meaning":"Generosity","reversed_meaning":"Debt","magical_manifestation":"Energy redistribution","personality_archetype":"Benefactor","core_themes":"giving","power_domains":"balance","behavioral_bias":"fair"},
  {"name":"Seven of Pentacles","arcana_type":"Minor","suit":"Pentacles","upright_meaning":"Patience","reversed_meaning":"Frustration","magical_manifestation":"Growth acceleration","personality_archetype":"Farmer","core_themes":"patience","power_domains":"growth","behavioral_bias":"patient"},
  {"name":"Eight of Pentacles","arcana_type":"Minor","suit":"Pentacles","upright_meaning":"Mastery","reversed_meaning":"Lack of focus","magical_manifestation":"Skill enhancement","personality_archetype":"Apprentice","core_themes":"work","power_domains":"craft","behavioral_bias":"focused"},
  {"name":"Nine of Pentacles","arcana_type":"Minor","suit":"Pentacles","upright_meaning":"Luxury","reversed_meaning":"Dependence","magical_manifestation":"Wealth aura","personality_archetype":"Independent achiever","core_themes":"success","power_domains":"earth","behavioral_bias":"self-reliant"},
  {"name":"Ten of Pentacles","arcana_type":"Minor","suit":"Pentacles","upright_meaning":"Legacy","reversed_meaning":"Instability","magical_manifestation":"Stability field","personality_archetype":"Legacy keeper","core_themes":"inheritance","power_domains":"structure","behavioral_bias":"traditional"},

  {"name":"Page of Cups","arcana_type":"Minor","suit":"Cups","upright_meaning":"Curiosity, emotional messages","reversed_meaning":"Emotional immaturity, insecurity","magical_manifestation":"Emotional signals, water sprites","personality_archetype":"Curious dreamer","core_themes":"curiosity, emotion","power_domains":"emotion, water, intuition","behavioral_bias":"naive, sensitive"},
  {"name":"Knight of Cups","arcana_type":"Minor","suit":"Cups","upright_meaning":"Romance, idealism","reversed_meaning":"Moodiness, unrealistic expectations","magical_manifestation":"Charm aura, emotional influence","personality_archetype":"Romantic seeker","core_themes":"idealism, emotion","power_domains":"emotion, influence","behavioral_bias":"passionate, dramatic"},
  {"name":"Queen of Cups","arcana_type":"Minor","suit":"Cups","upright_meaning":"Compassion, emotional stability","reversed_meaning":"Overemotional, dependency","magical_manifestation":"Healing waters, empathic shield","personality_archetype":"Empathic nurturer","core_themes":"care, empathy","power_domains":"healing, emotion","behavioral_bias":"nurturing, intuitive"},
  {"name":"King of Cups","arcana_type":"Minor","suit":"Cups","upright_meaning":"Emotional control, wisdom","reversed_meaning":"Manipulation, suppression","magical_manifestation":"Emotion control field","personality_archetype":"Balanced ruler","core_themes":"control, emotion","power_domains":"emotion, leadership","behavioral_bias":"calm, composed"},

  {"name":"Page of Swords","arcana_type":"Minor","suit":"Swords","upright_meaning":"Curiosity, vigilance","reversed_meaning":"Gossip, deceit","magical_manifestation":"Perception boost, scouting vision","personality_archetype":"Watcher","core_themes":"curiosity, awareness","power_domains":"mind, air, perception","behavioral_bias":"alert, restless"},
  {"name":"Knight of Swords","arcana_type":"Minor","suit":"Swords","upright_meaning":"Action, speed","reversed_meaning":"Recklessness, impulsiveness","magical_manifestation":"High-speed strikes","personality_archetype":"Aggressive warrior","core_themes":"action, speed","power_domains":"air, motion, combat","behavioral_bias":"impulsive, aggressive"},
  {"name":"Queen of Swords","arcana_type":"Minor","suit":"Swords","upright_meaning":"Clarity, independence","reversed_meaning":"Coldness, bitterness","magical_manifestation":"Precision cutting fields","personality_archetype":"Independent thinker","core_themes":"clarity, logic","power_domains":"mind, precision","behavioral_bias":"sharp, detached"},
  {"name":"King of Swords","arcana_type":"Minor","suit":"Swords","upright_meaning":"Authority, intellect","reversed_meaning":"Abuse of power, manipulation","magical_manifestation":"Command over mental force","personality_archetype":"Strategist ruler","core_themes":"authority, intellect","power_domains":"mind, control","behavioral_bias":"logical, dominant"},

  {"name":"Page of Wands","arcana_type":"Minor","suit":"Wands","upright_meaning":"Exploration, excitement","reversed_meaning":"Lack of direction","magical_manifestation":"Spark ignition, scouting flames","personality_archetype":"Adventurer","core_themes":"exploration, energy","power_domains":"fire, movement","behavioral_bias":"curious, energetic"},
  {"name":"Knight of Wands","arcana_type":"Minor","suit":"Wands","upright_meaning":"Passion, action","reversed_meaning":"Impulsiveness, anger","magical_manifestation":"Flame dash, explosive charge","personality_archetype":"Hot-headed warrior","core_themes":"passion, action","power_domains":"fire, force","behavioral_bias":"reckless, bold"},
  {"name":"Queen of Wands","arcana_type":"Minor","suit":"Wands","upright_meaning":"Confidence, charisma","reversed_meaning":"Jealousy, insecurity","magical_manifestation":"Flame aura, inspiration field","personality_archetype":"Charismatic leader","core_themes":"confidence, influence","power_domains":"fire, influence","behavioral_bias":"confident, expressive"},
  {"name":"King of Wands","arcana_type":"Minor","suit":"Wands","upright_meaning":"Leadership, vision","reversed_meaning":"Domination, impulsiveness","magical_manifestation":"Command flames, battlefield control","personality_archetype":"Visionary ruler","core_themes":"vision, leadership","power_domains":"fire, command","behavioral_bias":"decisive, ambitious"},

  {"name":"Page of Pentacles","arcana_type":"Minor","suit":"Pentacles","upright_meaning":"Learning, opportunity","reversed_meaning":"Lack of progress","magical_manifestation":"Resource sensing, growth seeds","personality_archetype":"Student","core_themes":"learning, growth","power_domains":"earth, development","behavioral_bias":"focused, diligent"},
  {"name":"Knight of Pentacles","arcana_type":"Minor","suit":"Pentacles","upright_meaning":"Hard work, reliability","reversed_meaning":"Stubbornness, laziness","magical_manifestation":"Endurance armor, steady force","personality_archetype":"Worker","core_themes":"effort, persistence","power_domains":"earth, endurance","behavioral_bias":"slow, reliable"},
  {"name":"Queen of Pentacles","arcana_type":"Minor","suit":"Pentacles","upright_meaning":"Care, practicality","reversed_meaning":"Neglect, imbalance","magical_manifestation":"Growth fields, protective earth","personality_archetype":"Caretaker","core_themes":"care, stability","power_domains":"earth, nurturing","behavioral_bias":"practical, grounded"},
  {"name":"King of Pentacles","arcana_type":"Minor","suit":"Pentacles","upright_meaning":"Wealth, control","reversed_meaning":"Greed, materialism","magical_manifestation":"Resource domination, fortified terrain","personality_archetype":"Provider ruler","core_themes":"wealth, control","power_domains":"earth, structure","behavioral_bias":"disciplined, possessive"}
]


def seed_lore(session) -> int:
    """Insert or update all 78 Arcana (22 Major, 56 Minor)."""
    inserted_or_updated = 0
    all_cards = MAJOR_ARCANA + MINOR_ARCANA
    for card_data in all_cards:
        existing = session.exec(
            select(TarotCardLore).where(TarotCardLore.name == card_data["name"])
        ).first()
        if existing:
            # Update existing record
            for key, value in card_data.items():
                setattr(existing, key, value)
            session.add(existing)
            inserted_or_updated += 1
        else:
            session.add(TarotCardLore(**card_data))
            inserted_or_updated += 1
    session.commit()
    return inserted_or_updated


# ─── Abilities ───────────────────────────────────────────────────────────────
ABILITIES: list[dict] = [
  {"name":"Light Orb","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"light,utility,visibility,non-combat","card_name":"The Sun","description":"Conjures a floating orb of warm sunlight that illuminates dark areas."},
  {"name":"Minor Levitation","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"movement,utility,air,control","card_name":"The Fool","description":"Allows the caster or a small object to hover slightly above the ground."},
  {"name":"Gentle Flight","mana_cost":5,"energy_type":"upright","ability_category":"utility","tags":"movement,travel,air","card_name":"The Chariot","description":"Grants the ability to glide smoothly through the air for a short duration."},
  {"name":"Prestidigitation","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"utility,cosmetic,minor-magic","card_name":"The Magician","description":"Performs minor magical tricks, such as creating sparks, changing colors, or cleaning a small object."},
  {"name":"Cleanse Object","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"cleaning,utility,water","card_name":"Temperance","description":"Purifies and cleans an object, removing dirt, poison, or minor curses."},
  {"name":"Warmth Aura","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"support,heat,comfort","card_name":"The Empress","description":"Radiates a comforting warmth that protects against cold and soothes allies."},
  {"name":"Cooling Breeze","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"air,cooling,utility","card_name":"Temperance","description":"Summons a refreshing breeze that cools the area and clears away light smoke or fog."},
  {"name":"Minor Illusion","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"illusion,stealth,visual","card_name":"The Moon","description":"Creates a small, silent visual illusion to distract or deceive onlookers."},
  {"name":"Invisibility (Short)","mana_cost":5,"energy_type":"upright","ability_category":"utility","tags":"stealth,invisibility,escape","card_name":"The Hermit","description":"Bends light to become completely invisible to the naked eye for a brief moment."},
  {"name":"Silent Step","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"stealth,movement,sound","card_name":"The Hermit","description":"Muffles all sound produced by the caster's footsteps, allowing for complete stealth."},
  {"name":"Feather Fall","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"movement,air,defense","card_name":"The Fool","description":"Slows the descent of a falling creature or object, preventing fall damage."},
  {"name":"Spark Fireworks","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"cosmetic,light,festival","card_name":"The Sun","description":"Produces a harmless but spectacular array of magical sparks and colors in the air."},
  {"name":"Color Spray","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"illusion,visual,cosmetic","card_name":"The Magician","description":"Emits a dazzling flash of colored light that can temporarily disorient or entertain."},
  {"name":"Scent Bloom","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"environment,cosmetic,nature","card_name":"The Empress","description":"Fills the immediate area with the pleasant, calming scent of blooming flowers."},
  {"name":"Message Whisper","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"communication,mental,link","card_name":"The Lovers","description":"Sends a short, telepathic message to a willing target within sight."},
  {"name":"Minor Teleport","mana_cost":5,"energy_type":"upright","ability_category":"utility","tags":"movement,space,escape","card_name":"The World","description":"Instantly transports the caster a short distance to an unoccupied space they can see."},
  {"name":"Object Pull","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"control,telekinesis,object","card_name":"The Magician","description":"Uses telekinetic force to pull a small, unattended object directly into the caster's hand."},
  {"name":"Object Push","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"force,control,object","card_name":"The Emperor","description":"Exerts a burst of force to push an object or small creature away from the caster."},
  {"name":"Detect Magic","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"detection,perception,magic","card_name":"The High Priestess","description":"Reveals the presence of magical auras and enchantments in the surrounding area."},
  {"name":"Aura Reading","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"analysis,perception,mind","card_name":"The High Priestess","description":"Allows the caster to see the emotional or magical aura of a target, revealing their general intent or nature."},
  {"name":"Luck Nudge","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"probability,buff,randomness","card_name":"The Wheel of Fortune","description":"Subtly alters probability to grant a minor streak of good luck to an ally."},
  {"name":"Balance Field","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"support,balance,area","card_name":"Temperance","description":"Creates an area where extreme physical or magical forces are neutralized into a state of equilibrium."},
  {"name":"Minor Heal","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"healing,restoration","card_name":"The Star","description":"Channels restorative energy to mend minor wounds and soothe pain."},
  {"name":"Energy Shield (Weak)","mana_cost":4,"energy_type":"upright","ability_category":"utility","tags":"defense,shield,protection","card_name":"Strength","description":"Projects a frail barrier of energy that can absorb a small amount of incoming damage."},
  {"name":"Night Vision","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"vision,perception,night","card_name":"The Moon","description":"Grants the ability to see perfectly in mundane or magical darkness."},
  {"name":"Sound Dampening","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"stealth,sound,area","card_name":"The Hermit","description":"Creates a localized zone where all sounds are significantly muffled or entirely silenced."},
  {"name":"Time Slow (Minor)","mana_cost":6,"energy_type":"upright","ability_category":"utility","tags":"time,control,slow","card_name":"The Hanged Man","description":"Briefly dilates time, making the world appear to move slower for a few crucial seconds."},
  {"name":"Object Repair","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"repair,restoration,object","card_name":"Temperance","description":"Magically mends a single break or tear in a non-magical object."},
  {"name":"Plant Growth (Minor)","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"nature,growth,environment","card_name":"The Empress","description":"Accelerates the growth of nearby flora, causing vines or flowers to bloom instantly."},
  {"name":"Water Shape","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"water,control,element","card_name":"Temperance","description":"Allows the caster to telekinetically manipulate and shape a small volume of water."},
  {"name":"Minor Wind Push","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"air,control,object","description":"Generates a gentle gust that pushes small objects or creatures slightly backward.","card_name":"The Fool"},
  {"name":"Soft Landing","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"movement,safety,air","description":"Reduces fall impact by cushioning the descent with a light air current.","card_name":"The Fool"},
  {"name":"Random Blink","mana_cost":4,"energy_type":"upright","ability_category":"utility","tags":"movement,chaos,space","description":"Instantly teleports the caster a short random distance in any direction.","card_name":"The Fool"},
  {"name":"Arcane Grip","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"control,telekinesis,object","description":"Allows precise telekinetic manipulation of a small object at short range.","card_name":"The Magician"},
  {"name":"Thread Weave","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"utility,craft,precision","description":"Magically repairs or stitches small materials with perfect accuracy.","card_name":"The Magician"},
  {"name":"Rune Projection","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"symbol,magic,visual","description":"Projects glowing magical symbols that can convey information or warnings.","card_name":"The Magician"},
  {"name":"Hidden Pulse","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"detection,magic,perception","description":"Emits a subtle pulse that reveals hidden magical signatures nearby.","card_name":"The High Priestess"},
  {"name":"Mind Veil","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"illusion,stealth,mind","description":"Shrouds the caster’s presence from casual perception and weak detection.","card_name":"The High Priestess"},
  {"name":"Echo Sense","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"sound,perception,area","description":"Uses sound vibrations to map the immediate surroundings.","card_name":"The High Priestess"},
  {"name":"Soothing Field","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"healing,calm,area","description":"Creates a calming aura that reduces stress and minor discomfort.","card_name":"The Empress"},
  {"name":"Bloom Trigger","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"nature,growth,environment","description":"Accelerates plant growth in a small area instantly.","card_name":"The Empress"},
  {"name":"Food Enrichment","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"utility,food,enhance","description":"Enhances taste and nutritional value of simple food.","card_name":"The Empress"},
  {"name":"Stability Anchor","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"structure,ground,control","description":"Anchors objects or the caster firmly in place against external forces.","card_name":"The Emperor"},
  {"name":"Force Line","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"force,barrier,control","description":"Creates a thin invisible barrier that blocks minor movement.","card_name":"The Emperor"},
  {"name":"Command Pulse","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"control,command,area","description":"Emits a pulse that compels weak entities to pause briefly.","card_name":"The Emperor"},
  {"name":"Ritual Mark","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"ritual,symbol,magic","description":"Places a magical sigil that can be used for later rituals.","card_name":"The Hierophant"},
  {"name":"Blessing Whisper","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"support,faith,utility","description":"Imbues a target with a minor blessing that enhances morale.","card_name":"The Hierophant"},
  {"name":"Seal Object","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"seal,protection,object","description":"Magically seals an object to prevent tampering or opening.","card_name":"The Hierophant"},
  {"name":"Bond Link","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"connection,communication,link","description":"Creates a temporary mental link between two willing targets.","card_name":"The Lovers"},
  {"name":"Emotion Sync","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"emotion,link,mental","description":"Aligns emotional states between connected individuals.","card_name":"The Lovers"},
  {"name":"Shared Vision","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"vision,link,perception","description":"Allows one target to see through another’s perspective briefly.","card_name":"The Lovers"},
  {"name":"Momentum Boost","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"movement,speed,force","description":"Temporarily increases movement speed in a straight path.","card_name":"The Chariot"},
  {"name":"Directional Pull","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"movement,control,force","description":"Pulls the caster slightly toward a chosen direction.","card_name":"The Chariot"},
  {"name":"Path Stabilize","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"movement,balance,travel","description":"Ensures stable footing on uneven or hazardous terrain.","card_name":"The Chariot"},
  {"name":"Inner Fortify","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"buff,defense,endurance","description":"Strengthens the body against fatigue and minor harm.","card_name":"Strength"},
  {"name":"Pain Dampener","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"support,body,control","description":"Reduces perceived pain without healing injuries.","card_name":"Strength"},
  {"name":"Focus Channel","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"mind,control,stability","description":"Enhances concentration and mental clarity temporarily.","card_name":"Strength"},
  {"name":"Shadow Fade","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"stealth,shadow,concealment","description":"Blends the caster into shadows, reducing visibility.","card_name":"The Hermit"},
  {"name":"Presence Null","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"stealth,aura,concealment","description":"Suppresses magical and physical presence signatures.","card_name":"The Hermit"},
  {"name":"Light Dim","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"light,control,environment","description":"Reduces ambient light intensity in a small area.","card_name":"The Hermit"},
  {"name":"Probability Tilt","mana_cost":4,"energy_type":"upright","ability_category":"utility","tags":"luck,probability,buff","description":"Slightly increases the likelihood of favorable outcomes.","card_name":"The Wheel of Fortune"},
  {"name":"Outcome Nudge","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"chance,control,randomness","description":"Subtly alters random events toward a desired direction.","card_name":"The Wheel of Fortune"},
  {"name":"Event Shift","mana_cost":5,"energy_type":"upright","ability_category":"utility","tags":"probability,change,utility","description":"Alters the immediate course of an unfolding minor event.","card_name":"The Wheel of Fortune"},
  {"name":"Truth Pulse","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"truth,detect,perception","description":"Reveals illusions or hidden deceptions nearby.","card_name":"Justice"},
  {"name":"Balance Check","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"balance,analysis,utility","description":"Evaluates the equilibrium of magical or physical states.","card_name":"Justice"},
  {"name":"Fair Bind","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"constraint,rule,control","description":"Restrains actions that violate defined conditions.","card_name":"Justice"},
  {"name":"Stasis Hold","mana_cost":4,"energy_type":"upright","ability_category":"utility","tags":"time,freeze,control","description":"Temporarily freezes a small object in time.","card_name":"The Hanged Man"},
  {"name":"Gravity Flip","mana_cost":5,"energy_type":"upright","ability_category":"utility","tags":"gravity,control,environment","description":"Reverses gravity briefly in a limited area.","card_name":"The Hanged Man"},
  {"name":"Temporal Pause","mana_cost":6,"energy_type":"upright","ability_category":"utility","tags":"time,control,slow","description":"Slows time slightly for nearby objects or entities.","card_name":"The Hanged Man"},
  {"name":"Decay Touch","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"decay,transform,object","description":"Accelerates natural decay of non-living materials.","card_name":"Death"},
  {"name":"Renew Pulse","mana_cost":4,"energy_type":"upright","ability_category":"utility","tags":"renewal,cycle,energy","description":"Restores vitality to worn or depleted objects.","card_name":"Death"},
  {"name":"Form Shift","mana_cost":5,"energy_type":"upright","ability_category":"utility","tags":"transform,change,body","description":"Temporarily alters the physical form slightly.","card_name":"Death"},
  {"name":"Energy Blend","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"fusion,balance,element","description":"Combines two energy types into a stable hybrid form.","card_name":"Temperance"},
  {"name":"Flow Stabilize","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"balance,flow,energy","description":"Stabilizes fluctuating magical energy flows.","card_name":"Temperance"},
  {"name":"Element Mix","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"element,fusion,control","description":"Mixes elemental properties without causing conflict.","card_name":"Temperance"},
  {"name":"Chain Pull","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"control,bind,object","description":"Pulls targets using conjured energy chains.","card_name":"The Devil"},
  {"name":"Desire Amplify","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"emotion,influence,control","description":"Intensifies a target’s current desire or motivation.","card_name":"The Devil"},
  {"name":"Shadow Bind","mana_cost":4,"energy_type":"upright","ability_category":"utility","tags":"shadow,control,restriction","description":"Restrains movement using shadow-like bindings.","card_name":"The Devil"},
  {"name":"Shock Pulse","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"disruption,energy,area","description":"Releases a pulse that disrupts minor magical effects.","card_name":"The Tower"},
  {"name":"Structure Break","mana_cost":4,"energy_type":"upright","ability_category":"utility","tags":"disruption,object,force","description":"Weakens structural integrity of objects.","card_name":"The Tower"},
  {"name":"Impact Wave","mana_cost":4,"energy_type":"upright","ability_category":"utility","tags":"shock,area,force","description":"Sends a force wave that pushes objects outward.","card_name":"The Tower"},
  {"name":"Guiding Light","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"light,guide,utility","description":"Creates a light that subtly guides the user’s direction.","card_name":"The Star"},
  {"name":"Hope Pulse","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"support,emotion,restore","description":"Boosts morale and emotional stability in an area.","card_name":"The Star"},
  {"name":"Clarity Beam","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"light,clarity,vision","description":"Enhances visual clarity and removes distortions.","card_name":"The Star"},
  {"name":"Dream Walk","mana_cost":4,"energy_type":"upright","ability_category":"utility","tags":"dream,illusion,mind","description":"Allows brief interaction with dream-like states.","card_name":"The Moon"},
  {"name":"Fear Illusion","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"illusion,fear,mind","description":"Creates illusions based on subconscious fears.","card_name":"The Moon"},
  {"name":"Mist Veil","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"illusion,environment,concealment","description":"Summons a mist that obscures vision.","card_name":"The Moon"},
  {"name":"Radiant Glow","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"light,energy,visibility","description":"Emits steady radiant light from the caster.","card_name":"The Sun"},
  {"name":"Heat Pulse","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"heat,energy,area","description":"Releases a wave of warmth across a small area.","card_name":"The Sun"},
  {"name":"Energy Flare","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"light,energy,burst","description":"Produces a brief flash of concentrated light energy.","card_name":"The Sun"},
  {"name":"Awaken Pulse","mana_cost":4,"energy_type":"upright","ability_category":"utility","tags":"revival,energy,soul","description":"Stimulates dormant energy within a target.","card_name":"Judgment"},
  {"name":"Clarity Call","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"mind,clarity,awareness","description":"Sharpens awareness and removes confusion.","card_name":"Judgment"},
  {"name":"Recall Echo","mana_cost":4,"energy_type":"upright","ability_category":"utility","tags":"memory,echo,time","description":"Retrieves recent memories with perfect clarity.","card_name":"Judgment"},
  {"name":"Spatial Fold","mana_cost":5,"energy_type":"upright","ability_category":"utility","tags":"space,teleport,control","description":"Folds space to shorten distance between two points.","card_name":"The World"},
  {"name":"Zone Anchor","mana_cost":4,"energy_type":"upright","ability_category":"utility","tags":"space,stability,area","description":"Stabilizes a region against spatial disturbances.","card_name":"The World"},
  {"name":"Reality Align","mana_cost":5,"energy_type":"upright","ability_category":"utility","tags":"space,balance,control","description":"Realigns local reality to a stable configuration.","card_name":"The World"},
  {"name":"Self Dry","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"water,utility,cleaning","description":"Instantly removes moisture from clothes or surfaces.","card_name":"Temperance"},
  {"name":"Perfect Temperature","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"comfort,environment,utility","description":"Adjusts the temperature of a small area to a comfortable level.","card_name":"Temperance"},
  {"name":"Auto Tie","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"utility,object,precision","description":"Ties knots or fastens small objects instantly.","card_name":"The Magician"},
  {"name":"Page Turn","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"utility,object,minor-magic","description":"Turns pages of a book automatically while reading.","card_name":"The Magician"},
  {"name":"Pocket Light","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"light,utility,visibility","description":"Creates a small floating light that follows the caster.","card_name":"The Sun"},
  {"name":"Glow Mark","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"light,marking,utility","description":"Places a glowing mark on a surface for easy navigation.","card_name":"The Star"},
  {"name":"Trail Sparkles","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"cosmetic,light,fun","description":"Leaves a brief trail of sparkles behind movement.","card_name":"The Sun"},
  {"name":"Flavor Shift","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"food,utility,cosmetic","description":"Changes the flavor of food or drink temporarily.","card_name":"The Empress"},
  {"name":"Fresh Preserve","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"food,utility,stability","description":"Prevents food from spoiling for a short duration.","card_name":"Temperance"},
  {"name":"Quick Chill","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"temperature,food,utility","description":"Rapidly cools small items or drinks.","card_name":"Temperance"},
  {"name":"Scent Mask","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"stealth,environment,utility","description":"Removes or alters scent to avoid detection.","card_name":"The Moon"},
  {"name":"Pleasant Aroma","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"cosmetic,environment,utility","description":"Creates a pleasant smell in the surrounding area.","card_name":"The Empress"},
  {"name":"Air Freshen","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"air,environment,utility","description":"Cleans stale or polluted air in a small space.","card_name":"Temperance"},
  {"name":"Tiny Sound","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"sound,illusion,utility","description":"Creates a faint harmless sound at a chosen point.","card_name":"The Moon"},
  {"name":"Whisper Carry","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"communication,air,utility","description":"Carries a whisper directly to a target within range.","card_name":"The Lovers"},
  {"name":"Echo Repeat","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"sound,utility,fun","description":"Repeats a short phrase as a fading echo.","card_name":"The High Priestess"},
  {"name":"Hair Style","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"cosmetic,appearance,utility","description":"Instantly changes hairstyle temporarily.","card_name":"The Empress"},
  {"name":"Clean Garment","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"cleaning,utility,object","description":"Removes dirt and stains from clothing.","card_name":"Temperance"},
  {"name":"Color Shift","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"cosmetic,illusion,visual","description":"Changes the color of an object briefly.","card_name":"The Magician"},
  {"name":"Mini Illusion Toy","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"illusion,fun,cosmetic","description":"Creates a tiny harmless illusion for entertainment.","card_name":"The Moon"},
  {"name":"Spark Flicker","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"light,cosmetic,fun","description":"Generates harmless sparks for visual effect.","card_name":"The Sun"},
  {"name":"Glow Pulse","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"light,signal,utility","description":"Emits a rhythmic glow useful for signaling.","card_name":"The Star"},
  {"name":"Object Locate","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"detection,utility,object","description":"Points toward a nearby known object.","card_name":"The High Priestess"},
  {"name":"Lost Item Recall","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"memory,utility,perception","description":"Helps recall the last location of an item.","card_name":"Judgment"},
  {"name":"Step Cushion","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"movement,stealth,utility","description":"Softens footsteps to reduce noise.","card_name":"The Hermit"},
  {"name":"Balance Assist","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"movement,balance,utility","description":"Helps maintain balance on uneven surfaces.","card_name":"The Chariot"},
  {"name":"Grip Boost","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"movement,body,utility","description":"Improves grip strength for climbing or holding.","card_name":"Strength"},
  {"name":"Tiny Lift","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"movement,object,utility","description":"Lifts a small object slightly off the ground.","card_name":"The Magician"},
  {"name":"Float Cup","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"object,utility,fun","description":"Makes a small object float beside you.","card_name":"The Fool"},
  {"name":"Door Knock Signal","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"sound,utility,signal","description":"Creates a knocking sound on a surface remotely.","card_name":"The Magician"},
  {"name":"Light Blink Signal","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"light,signal,utility","description":"Flashes light in simple patterns for communication.","card_name":"The Sun"},
  {"name":"Mood Tint","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"emotion,environment,utility","description":"Subtly shifts the mood of a small area.","card_name":"The Star"},
  {"name":"Calm Touch","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"emotion,healing,utility","description":"Soothes anxiety or stress in a target.","card_name":"The Star"},
  {"name":"Path Hint","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"guidance,utility,perception","description":"Provides a subtle sense of the correct direction.","card_name":"The Wheel of Fortune"},
  {"name":"Coin Flip Favor","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"luck,fun,utility","description":"Slightly biases a trivial random outcome.","card_name":"The Wheel of Fortune"},
  {"name":"Mirror Shine","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"visual,utility,cleaning","description":"Polishes reflective surfaces instantly.","card_name":"Temperance"},
  {"name":"Glass Repair","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"repair,object,utility","description":"Fixes small cracks in glass objects.","card_name":"Temperance"},
  {"name":"Chaos Leap Strike","mana_cost":16,"energy_type":"upright","ability_category":"combat","tags":"dash,burst,unpredictable","card_name":"The Fool","description":"Leap unpredictably to a target, striking with chaotic force and evading retaliation.","base_damage":140,"base_heal":None,"scaling_factor":1.2,"is_aoe":False,"aoe_radius":0,"applies_status":"evasion","status_duration":1,"status_value":30,"status_stackable":False},
  {"name":"Arcane Convergence","mana_cost":18,"energy_type":"upright","ability_category":"combat","tags":"magic,burst,precision","card_name":"The Magician","description":"Focus pure will into a precise arcane blast that strikes a single enemy with amplified force.","base_damage":160,"base_heal":None,"scaling_factor":1.3,"is_aoe":False,"aoe_radius":0,"applies_status":None,"status_duration":0,"status_value":0,"status_stackable":False},
  {"name":"Veil of Silence","mana_cost":17,"energy_type":"upright","ability_category":"combat","tags":"control,psychic,aoe","card_name":"The High Priestess","description":"Release a psychic wave that damages enemies and suppresses their abilities.","base_damage":120,"base_heal":None,"scaling_factor":1.1,"is_aoe":True,"aoe_radius":3.5,"applies_status":"silence","status_duration":2,"status_value":1,"status_stackable":False},
  {"name":"Thorn Dominion","mana_cost":20,"energy_type":"upright","ability_category":"combat","tags":"aoe,nature,dot","card_name":"The Empress","description":"Summon living vines that lash enemies and inflict continuous damage.","base_damage":130,"base_heal":None,"scaling_factor":1.2,"is_aoe":True,"aoe_radius":4.0,"applies_status":"bleed","status_duration":3,"status_value":20,"status_stackable":True},
  {"name":"Imperial Crush","mana_cost":22,"energy_type":"upright","ability_category":"combat","tags":"heavy,control,stagger","card_name":"The Emperor","description":"Strike with overwhelming authority, dealing heavy damage and staggering the target.","base_damage":190,"base_heal":None,"scaling_factor":1.3,"is_aoe":False,"aoe_radius":0,"applies_status":"stun","status_duration":1,"status_value":1,"status_stackable":False},
  {"name":"Judgment Pulse","mana_cost":19,"energy_type":"upright","ability_category":"combat","tags":"aoe,radiant,purge","card_name":"The Hierophant","description":"Emit a sacred pulse that damages enemies and weakens corrupted targets.","base_damage":135,"base_heal":None,"scaling_factor":1.2,"is_aoe":True,"aoe_radius":3.5,"applies_status":"weaken","status_duration":2,"status_value":15,"status_stackable":False},
  {"name":"Twin Strike Resonance","mana_cost":18,"energy_type":"upright","ability_category":"combat","tags":"dual-hit,combo,burst","card_name":"The Lovers","description":"Strike twice in resonance, dealing increased damage if target is already affected.","base_damage":150,"base_heal":None,"scaling_factor":1.25,"is_aoe":False,"aoe_radius":0,"applies_status":None,"status_duration":0,"status_value":0,"status_stackable":False},
  {"name":"Momentum Breaker","mana_cost":21,"energy_type":"upright","ability_category":"combat","tags":"dash,aoe,impact","card_name":"The Chariot","description":"Charge forward with unstoppable momentum, damaging all enemies in path.","base_damage":160,"base_heal":None,"scaling_factor":1.2,"is_aoe":True,"aoe_radius":4.5,"applies_status":"knockback","status_duration":1,"status_value":1,"status_stackable":False},
  {"name":"Beastbreaker Slam","mana_cost":20,"energy_type":"upright","ability_category":"combat","tags":"melee,burst,stagger","card_name":"Strength","description":"Deliver a powerful slam that crushes resistance and staggers enemies.","base_damage":170,"base_heal":None,"scaling_factor":1.2,"is_aoe":False,"aoe_radius":0,"applies_status":"stagger","status_duration":2,"status_value":1,"status_stackable":False},
  {"name":"Focused Lantern Burst","mana_cost":17,"energy_type":"upright","ability_category":"combat","tags":"precision,critical,light","card_name":"The Hermit","description":"Release concentrated light that strikes a critical weakness.","base_damage":150,"base_heal":None,"scaling_factor":1.35,"is_aoe":False,"aoe_radius":0,"applies_status":"expose","status_duration":2,"status_value":20,"status_stackable":False},
  {"name":"Entropy Surge","mana_cost":19,"energy_type":"upright","ability_category":"combat","tags":"aoe,random,chaos","card_name":"The Wheel of Fortune","description":"Unleash chaotic energy dealing variable damage across enemies.","base_damage":140,"base_heal":None,"scaling_factor":1.15,"is_aoe":True,"aoe_radius":4.0,"applies_status":"random-debuff","status_duration":2,"status_value":10,"status_stackable":False},
  {"name":"Balanced Execution","mana_cost":18,"energy_type":"upright","ability_category":"combat","tags":"true-damage,precision","card_name":"Justice","description":"Strike with perfect balance, ignoring defensive mitigation.","base_damage":165,"base_heal":None,"scaling_factor":1.3,"is_aoe":False,"aoe_radius":0,"applies_status":None,"status_duration":0,"status_value":0,"status_stackable":False},
  {"name":"Inversion Field","mana_cost":20,"energy_type":"upright","ability_category":"combat","tags":"aoe,slow,control","card_name":"The Hanged Man","description":"Distort gravity in an area, slowing enemies and damaging them over time.","base_damage":130,"base_heal":None,"scaling_factor":1.2,"is_aoe":True,"aoe_radius":4.0,"applies_status":"slow","status_duration":3,"status_value":30,"status_stackable":False},
  {"name":"Reaper's Cleave","mana_cost":24,"energy_type":"reversed","ability_category":"combat","tags":"aoe,execute,decay","card_name":"Death","description":"Slice through enemies with death energy, executing weakened targets.","base_damage":200,"base_heal":None,"scaling_factor":1.3,"is_aoe":True,"aoe_radius":3.0,"applies_status":"decay","status_duration":3,"status_value":25,"status_stackable":True},
  {"name":"Elemental Balance Burst","mana_cost":18,"energy_type":"upright","ability_category":"combat","tags":"aoe,balanced,elemental","card_name":"Temperance","description":"Release balanced elemental energy dealing equalized damage.","base_damage":145,"base_heal":None,"scaling_factor":1.2,"is_aoe":True,"aoe_radius":3.5,"applies_status":None,"status_duration":0,"status_value":0,"status_stackable":False},
  {"name":"Chains of Ruin","mana_cost":23,"energy_type":"reversed","ability_category":"combat","tags":"bind,dot,control","card_name":"The Devil","description":"Bind enemies with dark chains that deal continuous damage.","base_damage":150,"base_heal":None,"scaling_factor":1.25,"is_aoe":False,"aoe_radius":0,"applies_status":"bind","status_duration":3,"status_value":1,"status_stackable":False},
  {"name":"Cataclysm Strike","mana_cost":28,"energy_type":"reversed","ability_category":"combat","tags":"aoe,burst,destruction","card_name":"The Tower","description":"Call down destructive force that devastates an area.","base_damage":220,"base_heal":None,"scaling_factor":1.4,"is_aoe":True,"aoe_radius":5.0,"applies_status":"burn","status_duration":3,"status_value":30,"status_stackable":True},
  {"name":"Starlight Impact","mana_cost":20,"energy_type":"upright","ability_category":"combat","tags":"aoe,magic,radiant","card_name":"The Star","description":"Summon falling starlight that strikes enemies in an area.","base_damage":160,"base_heal":None,"scaling_factor":1.25,"is_aoe":True,"aoe_radius":4.0,"applies_status":"burn","status_duration":2,"status_value":20,"status_stackable":False},
  {"name":"Phantom Eclipse","mana_cost":19,"energy_type":"reversed","ability_category":"combat","tags":"illusion,aoe,confuse","card_name":"The Moon","description":"Shroud the battlefield in illusion, damaging and confusing enemies.","base_damage":140,"base_heal":None,"scaling_factor":1.2,"is_aoe":True,"aoe_radius":4.0,"applies_status":"confuse","status_duration":2,"status_value":1,"status_stackable":False},
  {"name":"Solar Flare Burst","mana_cost":22,"energy_type":"upright","ability_category":"combat","tags":"aoe,burst,blind","card_name":"The Sun","description":"Release a blinding solar explosion that damages enemies.","base_damage":180,"base_heal":None,"scaling_factor":1.3,"is_aoe":True,"aoe_radius":4.5,"applies_status":"blind","status_duration":2,"status_value":25,"status_stackable":False},
  {"name":"Final Verdict","mana_cost":24,"energy_type":"upright","ability_category":"combat","tags":"execute,burst,judgment","card_name":"Judgment","description":"Call down judgment energy that scales with missing enemy health.","base_damage":190,"base_heal":None,"scaling_factor":1.35,"is_aoe":False,"aoe_radius":0,"applies_status":None,"status_duration":0,"status_value":0,"status_stackable":False},
  {"name":"World Collapse","mana_cost":26,"energy_type":"upright","ability_category":"combat","tags":"aoe,space,burst","card_name":"The World","description":"Compress and release space, dealing massive area damage.","base_damage":210,"base_heal":None,"scaling_factor":1.4,"is_aoe":True,"aoe_radius":5.0,"applies_status":"pull","status_duration":1,"status_value":1,"status_stackable":False},
  {"name":"Chaotic Spark","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"chaos,burst,random","description":"Releases a small unpredictable burst that damages a nearby target.","card_name":"The Fool"},
  {"name":"Erratic Pulse","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"chaos,aoe,minor","description":"Emits a weak chaotic pulse affecting enemies in a very small radius.","card_name":"The Fool"},
  {"name":"Unstable Jab","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"chaos,precision,fast","description":"Strikes quickly with unstable energy causing minor damage.","card_name":"The Fool"},
  {"name":"Arcane Bolt","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"energy,precision,projectile","description":"Fires a focused magical projectile at a single target.","card_name":"The Magician"},
  {"name":"Mana Flick","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"energy,quick,light","description":"Releases a quick flicker of energy for minor damage.","card_name":"The Magician"},
  {"name":"Control Burst","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"energy,control,burst","description":"Channels controlled energy into a small burst at close range.","card_name":"The Magician"},
  {"name":"Mind Sting","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"psychic,precision,mental","description":"Inflicts minor psychic damage directly to the target’s mind.","card_name":"The High Priestess"},
  {"name":"Thought Ripple","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"psychic,aoe,minor","description":"Sends a ripple that lightly disrupts nearby enemies’ thoughts.","card_name":"The High Priestess"},
  {"name":"Insight Strike","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"mental,precision,fast","description":"Targets a weak mental point for a quick precise hit.","card_name":"The High Priestess"},
  {"name":"Thorn Lash","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"nature,precision,damage","description":"Summons a vine whip to strike a nearby enemy.","card_name":"The Empress"},
  {"name":"Root Snare","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"nature,control,minor","description":"Entangles a target briefly causing minor damage.","card_name":"The Empress"},
  {"name":"Petal Burst","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"nature,burst,light","description":"Releases sharp petals in a short burst.","card_name":"The Empress"},
  {"name":"Force Jab","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"force,precision,impact","description":"Delivers a concentrated force strike to a single target.","card_name":"The Emperor"},
  {"name":"Pressure Wave","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"force,aoe,minor","description":"Pushes enemies back with a small pressure surge.","card_name":"The Emperor"},
  {"name":"Command Strike","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"control,precision,fast","description":"A swift controlled attack guided by authority.","card_name":"The Emperor"},
  {"name":"Sacred Spark","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"holy,light,precision","description":"Emits a small burst of sacred energy at a target.","card_name":"The Hierophant"},
  {"name":"Rite Pulse","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"holy,aoe,minor","description":"Radiates ritual energy that lightly damages nearby enemies.","card_name":"The Hierophant"},
  {"name":"Faith Strike","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"holy,precision,fast","description":"Delivers a quick faith-infused strike.","card_name":"The Hierophant"},
  {"name":"Bond Cut","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"spirit,precision,damage","description":"Cuts a target’s emotional link causing minor damage.","card_name":"The Lovers"},
  {"name":"Dual Pulse","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"energy,aoe,link","description":"Releases paired energy pulses that hit nearby enemies.","card_name":"The Lovers"},
  {"name":"Heart Strike","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"spirit,precision,fast","description":"Targets emotional vulnerability for quick damage.","card_name":"The Lovers"},
  {"name":"Dash Strike","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"movement,impact,precision","description":"Charges forward and strikes a target.","card_name":"The Chariot"},
  {"name":"Momentum Hit","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"force,burst,minor","description":"Uses built momentum to deal increased impact damage.","card_name":"The Chariot"},
  {"name":"Quick Ram","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"movement,fast,impact","description":"A rapid short-distance hit with minor force.","card_name":"The Chariot"},
  {"name":"Power Tap","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"body,precision,damage","description":"Channels inner strength into a focused strike.","card_name":"Strength"},
  {"name":"Resilience Burst","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"body,aoe,minor","description":"Releases inner force damaging nearby enemies slightly.","card_name":"Strength"},
  {"name":"Firm Strike","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"body,fast,precision","description":"A controlled and steady attack.","card_name":"Strength"},
  {"name":"Hidden Cut","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"stealth,precision,damage","description":"A concealed strike that deals moderate damage.","card_name":"The Hermit"},
  {"name":"Shadow Pulse","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"shadow,aoe,minor","description":"Releases a dim pulse from the shadows.","card_name":"The Hermit"},
  {"name":"Silent Jab","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"stealth,fast,precision","description":"A quick unseen strike.","card_name":"The Hermit"},
  {"name":"Luck Strike","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"luck,random,damage","description":"Deals damage with slightly unpredictable results.","card_name":"The Wheel of Fortune"},
  {"name":"Chance Pulse","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"luck,aoe,minor","description":"A random energy pulse hitting nearby enemies.","card_name":"The Wheel of Fortune"},
  {"name":"Fortune Tap","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"luck,fast,precision","description":"A quick strike influenced by chance.","card_name":"The Wheel of Fortune"},
  {"name":"Balanced Cut","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"precision,cut,damage","description":"A perfectly balanced attack.","card_name":"Justice"},
  {"name":"Equal Pulse","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"balance,aoe,minor","description":"Damages enemies evenly within a small radius.","card_name":"Justice"},
  {"name":"Fair Strike","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"precision,fast,cut","description":"A quick and accurate strike.","card_name":"Justice"},
  {"name":"Time Tap","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"time,precision,damage","description":"Strikes while briefly slowing the target.","card_name":"The Hanged Man"},
  {"name":"Delay Pulse","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"time,aoe,minor","description":"A slow pulse that damages enemies slightly.","card_name":"The Hanged Man"},
  {"name":"Stall Hit","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"time,fast,precision","description":"A quick hit that disrupts timing.","card_name":"The Hanged Man"},
  {"name":"Decay Touch","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"decay,precision,damage","description":"Inflicts gradual damage through decay.","card_name":"Death"},
  {"name":"Rot Pulse","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"decay,aoe,minor","description":"A spreading decay pulse affecting nearby enemies.","card_name":"Death"},
  {"name":"End Strike","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"decay,fast,damage","description":"A swift strike that weakens the target.","card_name":"Death"},
  {"name":"Balance Hit","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"balance,precision,damage","description":"A controlled strike maintaining equilibrium.","card_name":"Temperance"},
  {"name":"Harmony Pulse","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"balance,aoe,minor","description":"Releases balanced energy damaging nearby foes.","card_name":"Temperance"},
  {"name":"Calm Strike","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"balance,fast,precision","description":"A steady and controlled attack.","card_name":"Temperance"},
  {"name":"Chain Snap","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"control,bind,damage","description":"Strikes with binding force.","card_name":"The Devil"},
  {"name":"Dark Pulse","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"shadow,aoe,minor","description":"Releases a dark energy pulse.","card_name":"The Devil"},
  {"name":"Grip Strike","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"control,fast,damage","description":"A quick controlling strike.","card_name":"The Devil"},
  {"name":"Shock Hit","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"shock,impact,damage","description":"A sudden burst of impact damage.","card_name":"The Tower"},
  {"name":"Crack Pulse","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"shock,aoe,minor","description":"Creates small disruptive cracks of energy.","card_name":"The Tower"},
  {"name":"Break Jab","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"impact,fast,damage","description":"A quick destructive hit.","card_name":"The Tower"},
  {"name":"Light Strike","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"light,precision,damage","description":"A focused beam of light damage.","card_name":"The Star"},
  {"name":"Glow Pulse","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"light,aoe,minor","description":"A soft radiant pulse damaging nearby enemies.","card_name":"The Star"},
  {"name":"Hope Hit","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"light,fast,damage","description":"A quick radiant strike.","card_name":"The Star"},
  {"name":"Shadow Sting","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"illusion,precision,damage","description":"A deceptive shadow attack.","card_name":"The Moon"},
  {"name":"Night Pulse","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"illusion,aoe,minor","description":"A dim wave of illusionary energy.","card_name":"The Moon"},
  {"name":"Mist Jab","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"illusion,fast,damage","description":"A quick concealed hit.","card_name":"The Moon"},
  {"name":"Sun Spark","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"light,energy,damage","description":"A bright energy strike.","card_name":"The Sun"},
  {"name":"Radiant Pulse","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"light,aoe,minor","description":"A glowing wave damaging nearby enemies.","card_name":"The Sun"},
  {"name":"Flash Hit","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"light,fast,damage","description":"A quick flash attack.","card_name":"The Sun"},
  {"name":"Soul Tap","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"soul,precision,damage","description":"Deals minor damage to the target’s essence.","card_name":"Judgment"},
  {"name":"Awaken Pulse","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"soul,aoe,minor","description":"A wave that disrupts nearby enemies’ vitality.","card_name":"Judgment"},
  {"name":"Call Strike","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"soul,fast,damage","description":"A quick spiritual hit.","card_name":"Judgment"},
  {"name":"Space Cut","mana_cost":3,"energy_type":"upright","ability_category":"combat","tags":"space,precision,damage","description":"Slices space to damage a target.","card_name":"The World"},
  {"name":"Warp Pulse","mana_cost":4,"energy_type":"upright","ability_category":"combat","tags":"space,aoe,minor","description":"A small spatial distortion pulse.","card_name":"The World"},
  {"name":"Fold Strike","mana_cost":2,"energy_type":"upright","ability_category":"combat","tags":"space,fast,damage","description":"A quick spatial distortion hit.","card_name":"The World"}
]

def seed_abilities(session) -> int:
    """Insert or update abilities linked to cards."""
    inserted_or_updated = 0
    for ability_data in ABILITIES:
        # Resolve card_id
        card_name = ability_data.pop("card_name")
        card = session.exec(
            select(TarotCardLore).where(TarotCardLore.name == card_name)
        ).first()
        
        if not card:
            print(f"  [Warning] Card '{card_name}' not found for ability '{ability_data['name']}'")
            continue
            
        ability_data["card_id"] = card.id
        
        existing = session.exec(
            select(TarotAbility).where(TarotAbility.name == ability_data["name"])
        ).first()
        
        if existing:
            for key, value in ability_data.items():
                setattr(existing, key, value)
            session.add(existing)
            inserted_or_updated += 1
        else:
            session.add(TarotAbility(**ability_data))
            inserted_or_updated += 1
            
    session.commit()
    return inserted_or_updated


def main():
    print("Seeding AI RPG database...")

    # 1. Create tables
    create_db_and_tables()
    print("  - Tables created")

    with get_session() as session:
        # 2. Create ROOT (WORLD_CORE) entity + GlobalConfig
        root = init_root(session)
        print(f"  - ROOT entity ready (id={root.id})")

        # 3. Seed 78 Arcana cards (Major + Minor)
        count = seed_lore(session)
        total = session.exec(select(TarotCardLore)).all()
        if count > 0:
            print(f"  - Inserted/Updated {count} Arcana ({len(total)} total in DB)")
        else:
            print(f"  - Lore already seeded ({len(total)} cards in DB)")

        # 4. Seed Abilities
        ability_count = seed_abilities(session)
        total_abilities = session.exec(select(TarotAbility)).all()
        if ability_count > 0:
            print(f"  - Inserted/Updated {ability_count} Abilities ({len(total_abilities)} total in DB)")
        else:
            print(f"  - Abilities already seeded ({len(total_abilities)} total in DB)")

    print("\nSeed complete. The world is ready.")


if __name__ == "__main__":
    main()
