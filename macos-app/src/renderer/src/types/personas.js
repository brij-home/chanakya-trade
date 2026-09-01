/**
 * @file personas.js
 * Multi-Agent Personas & Council Consensus JSDoc Type Definitions
 * Maps to agent/personas.py and agent/multi_agent.py
 */

/**
 * @typedef {'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL' | 'STAND_DOWN'} PersonaVerdict
 */

/**
 * @typedef {'buffett' | 'munger' | 'lynch' | 'jhunjhunwala' | 'kedia' | 'minervini' | 'wyckoff' | 'oneil' | 'soros' | 'simons' | 'taleb' | 'smc' | 'forensic'} PersonaId
 */

/**
 * @typedef {Object} PersonaSignal
 * @property {PersonaId} id - Unique persona identifier
 * @property {string} name - Persona display name (e.g. 'Mark Minervini')
 * @property {string} title - Philosophy subtitle (e.g. 'SEPA & VCP Momentum')
 * @property {string} icon - Emoji avatar icon
 * @property {PersonaVerdict} verdict - Stance / signal recommendation
 * @property {number} confidence - Conviction percentage (0 to 100)
 * @property {string} thesis - Analytical reasoning text
 * @property {Record<string, number|string|boolean>} [metrics] - Numerical framework checklist items
 * @property {string[]} [reasons] - Itemized conviction rationale points
 */

/**
 * @typedef {'breakout' | 'options_sniper' | 'multibagger' | 'macro_regime' | 'core_value'} CouncilId
 */

/**
 * @typedef {Object} CouncilConsensus
 * @property {CouncilId} id - Council identifier
 * @property {string} name - Council name (e.g. 'Breakout Council')
 * @property {string} icon - Council emblem
 * @property {string} desc - Ensemble membership description
 * @property {string} badge - Category badge (e.g. 'HIGH CONVICTION')
 * @property {PersonaVerdict} verdict - Synthesized council verdict
 * @property {number} score - Aggregate consensus score (0 to 100)
 * @property {PersonaId[]} members - List of member persona IDs
 * @property {string} thesis - Holistic synthesized council thesis
 * @property {PersonaSignal[]} [signals] - Detailed signals from each polled persona
 */

export {}
