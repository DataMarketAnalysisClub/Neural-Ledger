"""Keyword lexicon (English and Spanish) shared by the offline adapters: the rules decision model
and the scripted language model. Real models replace both; this keeps the system deterministic
and runnable with no network (demo recording, CI, test S10)."""

from __future__ import annotations

import re
from datetime import date

from ....domain.agent.amounts import extract_numbers
from ....domain.agent.questions import Intent
from ....domain.shared.month import Month

# Order = precedence when several intents match.
INTENT_PATTERNS: tuple[tuple[Intent, re.Pattern[str]], ...] = (
    (Intent.OUT_OF_SCOPE, re.compile(
        r"\b(stocks?|shares|acciones|crypto\w*|bitcoin|btc|ethereum|cripto\w*|forex|trading|invest(?:ing|ment|ments)?|"
        r"invert\w*|inversi[oó]n\w*|tax(?:es)?|impuestos?)\b", re.I)),
    # Before the others: "saldo" and "balance" alone mean a forecast, "regla" alone an action (ADR-037).
    (Intent.SET_LIQUIDITY_FLOOR, re.compile(
        r"\b(piso|saldo m[ií]nimo|m[ií]nimo de saldo|liquidity floor|floor|minimum balance|"
        r"(?:never|not) (?:go|goes|drop|drops|fall|falls) below|(?:baje|bajar|quede) (?:de|bajo|por debajo)|"
        r"(?:keep|mantener|mant[eé]n) (?:at least|al menos|como m[ií]nimo))\b", re.I)),
    (Intent.EXECUTE_ACTION, re.compile(
        r"\b(execute|ejecut\w*|go ahead|adelante|do it|hazlo|activate|activa\w*|transfer\w*|transfi\w*|move|mueve|send|env[ií]a)\b", re.I)),
    (Intent.EXPLAIN, re.compile(r"\b(what is an?|what's an?|what are|qu[eé] (?:es|son)|explain (?:what|how)|expl[ií]came|define)\b", re.I)),
    (Intent.SAVINGS_PLAN, re.compile(r"\b(sav(?:e|ing|ings)|ahorr\w*|set aside|put away|guardar)\b", re.I)),
    (Intent.AFFORD_PURCHASE, re.compile(
        r"\b(afford|buy|purchase|compr\w*|laptop|notebook|phone|cuotas?|installments?|make it work|alcanza)\b", re.I)),
    # Before a purchase check: "compré"/"bought" is money already spent, to log; "¿puedo comprar?" is a check (ADR-039).
    (Intent.LOG_EXPENSE, re.compile(
        r"\b(gast[eé]|gastamos|pagu[eé]|pagamos|compr[eé]|compramos|me gast[eé]|tuve un gasto|spent|paid|bought|"
        r"en efectivo|con efectivo|efectivo|cash|con tarjeta|con (?:la )?(?:d[eé]bito|cr[eé]dito)|by card|with (?:my )?card)\b", re.I)),
    # Before the surplus: "how much can I spend today" is the day-to-day check-in, not the one-off surplus (ADR-039).
    (Intent.SPENDING_CHECK, re.compile(
        r"\b(spend (?:today|now|this week|per day|a day|daily|until payday)|per day|a day|daily|por d[ií]a|al d[ií]a|diario|"
        r"gastar (?:hoy|ahora|esta semana|hasta)|until payday|hasta (?:el )?(?:pago|sueldo)|receipts?|boletas?|"
        r"how am i doing|c[oó]mo voy|my spending|mis gastos)\b", re.I)),
    (Intent.PROTECTED_SURPLUS, re.compile(r"\b(surplus|excedente|available|disponible|free money|how much can i|cu[aá]nto puedo|spare)\b", re.I)),
    (Intent.FORECAST, re.compile(
        r"\b(forecast|proyecci[oó]n|december|diciembre|next (?:few )?months|pr[oó]ximos meses|balance|saldo|crunch|cash ?flow|flujo)\b", re.I)),
    (Intent.SMALLTALK, re.compile(r"\b(hi|hello|hey|hola|thanks|thank you|gracias|buenas)\b", re.I)),
)

INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(ignore|disregard|forget|bypass|override|skip)\b.{0,40}\b(instructions?|rules?|limits?|polic(?:y|ies)|restrictions?|confirmation)\b", re.I),
    re.compile(r"\b(ignora|olvida|salta|omite)\b.{0,40}\b(instrucciones|reglas|l[ií]mites?|pol[ií]tica|confirmaci[oó]n)\b", re.I),
    re.compile(r"\b(system prompt|developer mode|jailbreak|you are now|act as|pretend to be)\b", re.I),
    re.compile(r"\b(new|add|nuevo|agrega)\b.{0,20}\b(beneficiary|payee|beneficiario|destinatario)\b", re.I),
    re.compile(r"\b(to|a la|al)\s+(?:account|cuenta)\s*(?:#|n[°º]?)?\s*\d{4,}", re.I),
    re.compile(r"\b(change|cambia)\b.{0,20}\b(limit|password|credentials|l[ií]mite|contrase[nñ]a|clave)\b", re.I),
)

TOLERANCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aggressive", re.compile(r"\b(aggressive|agresiv\w*|high risk|alto riesgo|risk[- ]taker)\b", re.I)),
    ("conservative", re.compile(r"\b(conservative|conservador\w*|no risk|sin riesgo|cautious|cauteloso|careful)\b", re.I)),
    ("moderate", re.compile(r"\b(moderate|moderad\w*|balanced|equilibrad\w*)\b", re.I)),
)

_MONTHS = {
    "january": 1, "enero": 1, "february": 2, "febrero": 2, "march": 3, "marzo": 3, "april": 4, "abril": 4,
    "may": 5, "mayo": 5, "june": 6, "junio": 6, "july": 7, "julio": 7, "august": 8, "agosto": 8,
    "september": 9, "septiembre": 9, "october": 10, "octubre": 10, "november": 11, "noviembre": 11,
    "december": 12, "diciembre": 12,
}
_INSTALLMENTS = re.compile(r"\b(\d{1,2})\s*(?:cuotas?|installments?|payments?|meses|months)\b", re.I)
_ISO_MONTH = re.compile(r"\b(20\d{2})-(0[1-9]|1[0-2])\b")
_NAMED_MONTH = re.compile(r"\b(?:in|from|starting|en|desde|a partir de)\s+(" + "|".join(_MONTHS) + r")\b", re.I)


def money_amounts(text: str) -> list[int]:
    return [int(n.value) for n in extract_numbers(text) if not n.is_percent and n.value >= 1000]


def installments(text: str) -> int | None:
    match = _INSTALLMENTS.search(text)
    return int(match.group(1)) if match else None


def mentioned_month(text: str, as_of: date | None) -> Month | None:
    iso = _ISO_MONTH.search(text)
    if iso:
        return Month(int(iso.group(1)), int(iso.group(2)))
    named = _NAMED_MONTH.search(text)
    if named and as_of:
        number = _MONTHS[named.group(1).lower()]
        year = as_of.year if number > as_of.month else as_of.year + 1
        return Month(year, number)
    return None
