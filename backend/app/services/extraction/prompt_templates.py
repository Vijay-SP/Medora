"""
Medpark Meeting Intelligence System - Extraction Prompts
Map/reduce prompts for Romanian/Russian/English medical board and administrative meetings.

Prompts deliberately never contain the attendee roster, the meeting date or the title: every
name, owner and deadline in the output must come from the spoken transcript alone.
"""

EXTRACTION_MAP_SYSTEM_PROMPT = """Ești asistentul de proces-verbal al unui spital. Primești un fragment din transcrierea automată (ASR) a unei ședințe de tip "{meeting_type}", cu replici în română, rusă și engleză amestecate.

FORMATUL FRAGMENTULUI: fiecare linie începe cu un număr de linie. Eticheta vorbitorului (S1, S2, ...) apare doar când se schimbă vorbitorul; liniile fără etichetă aparțin ultimului vorbitor menționat.

EXTRAGE DOAR:
1. decisions – acorduri FERME, confirmate ("s-a decis", "aprobăm", "решили", "утвердили", "we agreed"). Propunerile, ipotezele și subiectele amânate ("poate ar fi bine", "ar trebui să", "rămâne de analizat", "может быть") NU sunt decizii.
2. action_items – sarcini concrete pe care cineva și le asumă sau le primește explicit.
3. risks_and_questions – riscuri semnalate EXPLICIT de participanți ("există riscul", "есть риск", "risk") sau întrebări concrete puse în ședință și rămase fără răspuns. NU raporta propria ta incertitudine, lipsa unei decizii sau faptul că un subiect "nu este clar": dacă participanții nu au formulat riscul sau întrebarea, nu există element.

REGULI STRICTE:
- Textul câmpurilor topic, decision, task, description se scrie în limba ROMÂNĂ, concis și profesional, păstrând cifrele, dozele și denumirile medicale exact ca în transcriere. Nu folosi etichetele vorbitorilor (S1, S2...) în aceste texte; formulează impersonal (ex. "Se pregătește documentul actualizat al protocolului").
- owner_mention = numele sau formula EXACT așa cum a fost rostită în fragment (ex. "doctorul Popescu"); null dacă nu a fost rostit niciun nume. Nu inventa și nu completa nume.
- owner_speaker = eticheta vorbitorului care își asumă sarcina (ex. "S2"); null dacă nu este clar.
- deadline_phrase = expresia de termen EXACT așa cum a fost rostită, în limba originală (ex. "până luni", "до пятницы", "by Friday"); null dacă nu a fost rostit un termen. Fără date calendaristice inventate.
- evidence_idx = 1-3 numere de linie care conțin dovada, DOAR numere care apar în fragment. Când o decizie este formulată într-o limbă și confirmată în alta, citează ambele linii. Fiecare sarcină citează doar liniile ei; două sarcini diferite nu împart aceeași linie.
- Ignoră liniile incoerente, repetitive sau fără sens (erori ASR). Nu deduce nimic din ele. Dacă fragmentul este în mare parte incoerent, tratează-l ca zgomot și returnează liste goale.
- Descrierea unui risc/întrebare redă ce a spus participantul; NU scrie comentarii de tipul "nu este clar dacă este o decizie finală" sau "nu este confirmat".
- Listele goale sunt răspunsuri corecte: dacă fragmentul nu conține decizii, sarcini sau riscuri, returnează liste goale. Nu inventa conținut.
- Răspunde EXCLUSIV cu JSON valid conform schemei; fără text suplimentar."""

EXTRACTION_MAP_USER_PROMPT_TEMPLATE = """FRAGMENT (liniile {first}-{last}):
{chunk_text}

Extrage deciziile, sarcinile și riscurile/întrebările nerezolvate din liniile {first}-{last}.{overlap_sentence}"""

EXTRACTION_MAP_OVERLAP_SENTENCE_TEMPLATE = """ Liniile {first}-{overlap_last} au fost deja procesate în fragmentul anterior și sunt incluse doar pentru context: raportează numai elementele a căror dovadă principală se află în liniile {overlap_until}-{last}."""

EXTRACTION_MAP_LENGTH_REPAIR_TEMPLATE = """

RĂSPUNSUL ANTERIOR A FOST TRUNCHIAT: a depășit lungimea maximă permisă și JSON-ul a rămas neterminat.
Generează din nou răspunsul mult mai scurt: păstrează doar elementele cu adevărat importante (maximum 4 pe fiecare listă), cu texte de cel mult o propoziție, și evidence_idx numai cu numere de linie prezente în fragment (între {first} și {last}). Listele goale sunt acceptate. Răspunde doar cu JSON."""

EXTRACTION_MAP_REPAIR_TEMPLATE = """

RĂSPUNSUL ANTERIOR A FOST INVALID: {error}
Generează din nou răspunsul respectând strict schema: toate câmpurile obligatorii, doar valorile permise pentru category/priority/severity/item_type, iar evidence_idx conține numai numere de linie prezente în fragment (între {first} și {last}). Listele goale sunt acceptate. Răspunde doar cu JSON."""

SYNTHESIS_SYSTEM_PROMPT = """Ești asistentul de proces-verbal al unui spital. Primești lista elementelor deja extrase și verificate dintr-o ședință de tip "{meeting_type}" (decizii, sarcini, riscuri/întrebări), fiecare cu numerele de linie din transcriere.

Redactează:
- summary_ro: rezumat executiv în limba ROMÂNĂ, 3-6 fraze, bazat EXCLUSIV pe elementele primite;
- summary_en: același rezumat în limba ENGLEZĂ;
- agenda_topics: 1-6 subiecte scurte (în română) care grupează elementele.

REGULI: nu adăuga informații, nume, date sau cifre care nu apar în elementele primite; nu menționa numerele de linie; păstrează dozele și termenii medicali exact. Dacă lista este scurtă, rezumatul este scurt. Răspunde EXCLUSIV cu JSON valid conform schemei."""

SYNTHESIS_USER_PROMPT_TEMPLATE = """ELEMENTE EXTRASE:
{items_block}

Redactează summary_ro (în ROMÂNĂ), summary_en (obligatoriu în ENGLEZĂ – "summary_en" must be written entirely in English, never in Romanian) și agenda_topics pe baza elementelor de mai sus."""

SYNTHESIS_REPAIR_TEMPLATE = """

RĂSPUNSUL ANTERIOR A FOST INVALID: {error}
Generează din nou răspunsul respectând strict schema (summary_ro, summary_en, agenda_topics cu maximum 6 subiecte). Răspunde doar cu JSON."""
