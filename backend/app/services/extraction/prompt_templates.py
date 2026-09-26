"""
Medpark Meeting Intelligence System - Extraction Prompts
Map/reduce prompts for Romanian/Russian/English medical board and administrative meetings.

Prompts deliberately never contain the attendee roster, the meeting date or the title: every
owner and deadline in the output must come from the spoken transcript alone.

Attribution style: decision/task/description texts and the summaries attribute to the anonymous
speaker labels of the indexed transcript ("S3 a propus ...; S1 a aprobat"). The labels are the ONLY
way the model may name a person; the render layer (attribution_render) substitutes a reviewer-
confirmed name or the localized anonymous form at read time. owner_mention still carries the
verbatim spoken mention separately for resolve_owner.
"""

EXTRACTION_MAP_SYSTEM_PROMPT = """Ești asistentul de proces-verbal al unui spital. Primești un fragment din transcrierea automată (ASR) a unei ședințe de tip "{meeting_type}", cu replici în română, rusă și engleză amestecate.

FORMATUL FRAGMENTULUI: fiecare linie începe cu un număr de linie. Eticheta vorbitorului (S1, S2, ...) apare doar când se schimbă vorbitorul; liniile fără etichetă aparțin ultimului vorbitor menționat.

EXTRAGE DOAR:
1. decisions – acorduri FERME, confirmate ("s-a decis", "aprobăm", "решили", "утвердили", "we agreed"). Propunerile, ipotezele și subiectele amânate ("poate ar fi bine", "ar trebui să", "rămâne de analizat", "может быть") NU sunt decizii.
2. action_items – sarcini concrete pe care cineva și le asumă sau le primește explicit.
3. risks_and_questions – riscuri semnalate EXPLICIT de participanți ("există riscul", "есть риск", "risk") sau întrebări concrete puse în ședință și rămase fără răspuns. NU raporta propria ta incertitudine, lipsa unei decizii sau faptul că un subiect "nu este clar": dacă participanții nu au formulat riscul sau întrebarea, nu există element.

REGULI STRICTE:
- Textul câmpurilor topic, decision, task, description se scrie în limba ROMÂNĂ, concis și profesional, păstrând cifrele, dozele și denumirile medicale exact ca în transcriere.
- STIL DE ATRIBUIRE: câmpurile decision, task și description se redactează ca notițele unui facilitator, atribuind fiecare acțiune vorbitorului prin ETICHETA lui, EXACT așa cum apare în fragment (S1, S2, S3...). Exemple de stil:
  * decision: "S3 a propus …; S1 a aprobat."
  * task: "S2 va trimite … până vineri."
  * description: "S3 a semnalat riscul că …"
  Exemplele arată DOAR forma frazei: „…” se completează EXCLUSIV cu ce s-a spus în liniile citate; nu prelua niciun conținut din exemple.
  Eticheta este SINGURA formă permisă de a numi o persoană în aceste câmpuri: NU scrie nume proprii, NU scrie formule ca "doctorul X" sau "doamna Y" și NU inventa etichete care nu apar în fragment. Când nu se poate atribui, formulează impersonal.
- Persoană numită în fragment (ex. "S1: Doctorul Ionescu va actualiza ghidul până luni."): NU copia numele; task: "S1 a atribuit unui coleg actualizarea ghidului până luni.", owner_mention: "Doctorul Ionescu". Dacă persoana numită răspunde și își asumă sarcina, folosește eticheta ei ("S2 va actualiza ghidul").
- speakers = lista etichetelor (ex. ["S3", "S1"]) vorbitorilor pe care textul elementului îi atribuie, maximum 3, numai etichete care apar în liniile citate; listă goală dacă nu se poate atribui.
- owner_mention = numele sau formula EXACT așa cum a fost rostită în fragment (ex. "doctorul Ionescu"); null dacă nu a fost rostit niciun nume. Nu inventa și nu completa nume. Acesta este SINGURUL câmp în care poate apărea un nume.
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
Generează din nou răspunsul respectând strict schema: toate câmpurile obligatorii (inclusiv speakers, cu etichete S1, S2... din fragment), doar valorile permise pentru category/priority/severity/item_type, iar evidence_idx conține numai numere de linie prezente în fragment (între {first} și {last}). Listele goale sunt acceptate. Răspunde doar cu JSON."""

SYNTHESIS_SYSTEM_PROMPT = """Ești asistentul de proces-verbal al unui spital. Primești lista elementelor deja extrase și verificate dintr-o ședință de tip "{meeting_type}" (decizii [D], sarcini [A], riscuri/întrebări [R]), fiecare cu etichetele vorbitorilor atribuiți între paranteze (ex. "(S3, S1)").

Redactează:
- summary_ro: rezumat narativ scurt în limba ROMÂNĂ, 3-6 fraze, în stilul notițelor unui facilitator: cine a deschis ședința, cine a propus, cine a aprobat, cine ce va face. Vorbitorii se numesc EXCLUSIV prin etichetele lor, exact ca în elemente. Forma frazelor (conținutul „…” vine EXCLUSIV din elemente, nu din acest model): "S1 a deschis ședința cu … S3 a propus …, iar S1 a aprobat. S2 va … până vineri. S3 a semnalat riscul că …";
- summary_ru: același rezumat în limba RUSĂ, cu aceleași etichete (S1, S2...) neschimbate;
- summary_en: același rezumat în limba ENGLEZĂ, cu aceleași etichete (S1, S2...) neschimbate;
- agenda_topics: 1-6 subiecte scurte (în română) care grupează elementele.

REGULI: bazează-te EXCLUSIV pe elementele primite; nu adăuga informații, date sau cifre care nu apar în ele; NU scrie nume de persoane și NU inventa etichete care nu apar în elemente (etichetele sunt singura formă permisă de a numi pe cineva); dacă un element conține totuși un nume sau o formulă ca "doctorul X", NU le prelua: scrie "un coleg" (ex. "S1 a atribuit unui coleg actualizarea ghidului"); notațiile clinice (L5-S1, zgomotele S1 și S2) nu sunt etichete și se păstrează exact; nu menționa numerele de linie; păstrează dozele și termenii medicali exact. Dacă lista este scurtă, rezumatul este scurt. Răspunde EXCLUSIV cu JSON valid conform schemei."""

SYNTHESIS_USER_PROMPT_TEMPLATE = """ELEMENTE EXTRASE:
{items_block}

Redactează summary_ro (în ROMÂNĂ), summary_ru (în RUSĂ), summary_en (obligatoriu în ENGLEZĂ – "summary_en" must be written entirely in English, never in Romanian; keep the speaker labels S1, S2... exactly as given) și agenda_topics pe baza elementelor de mai sus, atribuind acțiunile vorbitorilor prin etichetele lor."""

SYNTHESIS_LENGTH_REPAIR_TEMPLATE = """

RĂSPUNSUL ANTERIOR A FOST TRUNCHIAT: a depășit lungimea maximă permisă și JSON-ul a rămas neterminat.
Generează din nou răspunsul MULT mai scurt: fiecare rezumat (summary_ro, summary_ru, summary_en) are cel mult 4 fraze scurte care grupează elementele asemănătoare și păstrează etichetele vorbitorilor (S1, S2...) exact; agenda_topics are cel mult 4 subiecte. Nu repeta fraze. Răspunde doar cu JSON."""

SYNTHESIS_REPAIR_TEMPLATE = """

RĂSPUNSUL ANTERIOR A FOST INVALID: {error}
Generează din nou răspunsul respectând strict schema (summary_ro, summary_ru, summary_en, agenda_topics cu maximum 6 subiecte). Răspunde doar cu JSON."""
