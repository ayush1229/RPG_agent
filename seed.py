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
  {"name":"Light Orb","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"light,utility,visibility,non-combat","card_name":"The Sun"},
  {"name":"Minor Levitation","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"movement,utility,air,control","card_name":"The Fool"},
  {"name":"Gentle Flight","mana_cost":5,"energy_type":"upright","ability_category":"utility","tags":"movement,travel,air","card_name":"The Chariot"},
  {"name":"Prestidigitation","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"utility,cosmetic,minor-magic","card_name":"The Magician"},
  {"name":"Cleanse Object","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"cleaning,utility,water","card_name":"Temperance"},
  {"name":"Warmth Aura","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"support,heat,comfort","card_name":"The Empress"},
  {"name":"Cooling Breeze","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"air,cooling,utility","card_name":"Temperance"},
  {"name":"Minor Illusion","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"illusion,stealth,visual","card_name":"The Moon"},
  {"name":"Invisibility (Short)","mana_cost":5,"energy_type":"upright","ability_category":"utility","tags":"stealth,invisibility,escape","card_name":"The Hermit"},
  {"name":"Silent Step","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"stealth,movement,sound","card_name":"The Hermit"},
  {"name":"Feather Fall","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"movement,air,defense","card_name":"The Fool"},
  {"name":"Spark Fireworks","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"cosmetic,light,festival","card_name":"The Sun"},
  {"name":"Color Spray","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"illusion,visual,cosmetic","card_name":"The Magician"},
  {"name":"Scent Bloom","mana_cost":1,"energy_type":"upright","ability_category":"utility","tags":"environment,cosmetic,nature","card_name":"The Empress"},
  {"name":"Message Whisper","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"communication,mental,link","card_name":"The Lovers"},
  {"name":"Minor Teleport","mana_cost":5,"energy_type":"upright","ability_category":"utility","tags":"movement,space,escape","card_name":"The World"},
  {"name":"Object Pull","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"control,telekinesis,object","card_name":"The Magician"},
  {"name":"Object Push","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"force,control,object","card_name":"The Emperor"},
  {"name":"Detect Magic","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"detection,perception,magic","card_name":"The High Priestess"},
  {"name":"Aura Reading","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"analysis,perception,mind","card_name":"The High Priestess"},
  {"name":"Luck Nudge","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"probability,buff,randomness","card_name":"The Wheel of Fortune"},
  {"name":"Balance Field","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"support,balance,area","card_name":"Temperance"},
  {"name":"Minor Heal","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"healing,restoration","card_name":"The Star"},
  {"name":"Energy Shield (Weak)","mana_cost":4,"energy_type":"upright","ability_category":"utility","tags":"defense,shield,protection","card_name":"Strength"},
  {"name":"Night Vision","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"vision,perception,night","card_name":"The Moon"},
  {"name":"Sound Dampening","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"stealth,sound,area","card_name":"The Hermit"},
  {"name":"Time Slow (Minor)","mana_cost":6,"energy_type":"upright","ability_category":"utility","tags":"time,control,slow","card_name":"The Hanged Man"},
  {"name":"Object Repair","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"repair,restoration,object","card_name":"Temperance"},
  {"name":"Plant Growth (Minor)","mana_cost":3,"energy_type":"upright","ability_category":"utility","tags":"nature,growth,environment","card_name":"The Empress"},
  {"name":"Water Shape","mana_cost":2,"energy_type":"upright","ability_category":"utility","tags":"water,control,element","card_name":"Temperance"}
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
