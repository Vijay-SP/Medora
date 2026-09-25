"""
Medpark Meeting Intelligence System - Multilingual Medical Glossary
Provides vocabulary injection and decoder prompt conditioning for Romanian/Russian/English code-switching.
"""

from typing import Optional


# High-frequency medical terms across Romanian, Russian, and English in Moldovan hospital meetings
MEDPARK_MEDICAL_VOCABULARY = [
    # Romanian Clinical & Administrative Terms
    "Medpark", "Spitalul Internațional Medpark", "Consiliul Medical", "Comitetul Director",
    "terapie intensivă", "ATI", "anestezie", "bloc operator", "chirurgie laparoscopică",
    "hemostază", "sutură", "protocol clinic", "analize de laborator", "hemoleucogramă",
    "tomografie computerizată", "CT", "RMN", "rezonanță magnetică", "cateterism",
    "angioplastie", "stent", "bypass coronarian", "cardiologie intervențională",
    "secția internare", "farmacie spitalicească", "antibioticoterapie", "consimțământ informat",
    "transfer interclinic", "raport de gardă", "termen limită", "responsabil", "aprobare buget",
    
    # Russian Clinical & Conversational Terms (Moldovan dialectal code-switching)
    "пациент", "история болезни", "назначение", "реанимация", "дежурный врач",
    "заведующий отделением", "срочно", "согласовать", "дозировка", "операционный блок",
    "анализы", "выписка", "консилиум", "перевод в палату", "давление", "препарат",
    "капельница", "рентген", "кардиограмма", "по протоколу", "давай решим",
    
    # English Clinical, IT & Management Jargon
    "guidelines", "workflow", "Standard Operating Procedure", "SOP", "compliance",
    "quality assurance", "KPI", "follow-up", "triage", "emergency room", "screening",
    "discharge summary", "monitoring", "checkpoint", "feedback", "roadmap", "audit"
]


def build_code_switch_prompt(
    agenda: Optional[str] = None,
    attendee_names: Optional[list[str]] = None,
    custom_terms: Optional[list[str]] = None
) -> str:
    """
    Constructs a high-impact multilingual initial_prompt for Whisper.
    Forces Whisper's decoder attention to maintain Romanian diacritics and Russian Cyrillic
    tokens simultaneously, preventing mono-lingual collapse on code-switching boundaries.
    """
    prompt_parts = [
        "Ședință medicală și administrativă Medpark. Discuție trilingvă (Română, Русский, English).",
        "Teme clinice: " + ", ".join(MEDPARK_MEDICAL_VOCABULARY[:25]) + ".",
        "Термины: " + ", ".join(MEDPARK_MEDICAL_VOCABULARY[25:40]) + "."
    ]

    if attendee_names:
        prompt_parts.append("Participanți: " + ", ".join(attendee_names) + ".")

    if agenda:
        prompt_parts.append(f"Ordinea de zi: {agenda}.")

    if custom_terms:
        prompt_parts.append("Termeni specifici: " + ", ".join(custom_terms) + ".")

    full_prompt = " ".join(prompt_parts)
    # Whisper initial_prompt is limited to approximately 224 tokens; keep it bounded
    return full_prompt[:800]
