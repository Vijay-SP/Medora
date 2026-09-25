"""
Medpark Meeting Intelligence System - Document Generation Engine
Produces immutable, versioned PDF and DOCX Minutes of Meeting supporting Romanian diacritics and Cyrillic.
"""

from pathlib import Path
from datetime import datetime
import os
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from fpdf import FPDF
from app.core.logging import logger
from app.models.meeting import Meeting
from app.models.extraction import MinutesOfMeeting


class PDFReport(FPDF):
    """Custom FPDF generator with Medpark styling."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.font_family_to_use = "Helvetica"
        # Check cross-platform Unicode font candidates (Windows Arial, Linux/Docker DejaVu, Liberation)
        font_candidates = [
            Path("C:/Windows/Fonts/arial.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
            Path("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
            Path("/usr/share/fonts/opentype/freefont/FreeSans.ttf"),
        ]
        for font_path in font_candidates:
            if font_path.exists():
                try:
                    self.add_font("AppUnicode", "", str(font_path))
                    self.font_family_to_use = "AppUnicode"
                    break
                except Exception:
                    pass

    def header(self):
        font_name = self.font_family_to_use if self.font_family_to_use != "Helvetica" else "Helvetica"
        style = "" if font_name != "Helvetica" else "B"
        self.set_font(font_name, style, 13)
        self.set_text_color(0, 51, 102)  # Hospital Navy Blue
        
        header_title = "SPITALUL INTERNATIONAL MEDPARK" if font_name == "Helvetica" else "SPITALUL INTERNAȚIONAL MEDPARK"
        self.cell(0, 8, header_title, new_x="LMARGIN", new_y="NEXT", align="L")
        
        sub_style = "" if font_name != "Helvetica" else "I"
        self.set_font(font_name, sub_style, 9)
        self.set_text_color(100, 100, 100)
        sub_text = "Sistem Inteligent de Documentare Offline a Sedintelor" if font_name == "Helvetica" else "Sistem Inteligent de Documentare Offline a Ședințelor"
        self.cell(0, 5, sub_text, new_x="LMARGIN", new_y="NEXT", align="L")
        
        self.ln(2)
        self.set_draw_color(0, 51, 102)
        self.set_line_width(0.5)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        font_name = self.font_family_to_use if self.font_family_to_use != "Helvetica" else "Helvetica"
        style = "" if font_name != "Helvetica" else "I"
        self.set_font(font_name, style, 8)
        self.set_text_color(128, 128, 128)
        foot_text = f"Pagina {self.page_no()} | Document Confidential de Uz Intern Medpark"
        self.cell(0, 10, foot_text, align="C")


class DocumentGenerator:
    """Generates official, evidence-linked PDF and DOCX reports."""

    def generate_all(self, meeting: Meeting, minutes: MinutesOfMeeting, pdf_out: Path, docx_out: Path) -> tuple[Path, Path]:
        """Generates both PDF and DOCX files for a given meeting revision."""
        pdf_path = self.generate_pdf(meeting, minutes, pdf_out)
        docx_path = self.generate_docx(meeting, minutes, docx_out)
        return pdf_path, docx_path

    def generate_docx(self, meeting: Meeting, minutes: MinutesOfMeeting, output_path: Path) -> Path:
        """Constructs formatted Word document (.docx) with tables and metadata."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc = Document()

        # Document Header
        title_p = doc.add_paragraph()
        title_run = title_p.add_run("PROCES-VERBAL AL ȘEDINȚEI (MINUTES OF MEETING)")
        title_run.bold = True
        title_run.font.size = Pt(16)
        title_run.font.color.rgb = RGBColor(0, 51, 102)

        subtitle_p = doc.add_paragraph()
        sub_run = subtitle_p.add_run(f"Spitalul Internațional Medpark | {meeting.meeting_type.value.upper()}")
        sub_run.font.size = Pt(11)
        sub_run.font.color.rgb = RGBColor(100, 100, 100)

        # Meeting Info Grid
        doc.add_heading("Informații Generale", level=2)
        info_table = doc.add_table(rows=4, cols=2)
        info_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        
        info_data = [
            ("Titlu Ședință:", meeting.title),
            ("Data și Ora:", meeting.scheduled_at.strftime("%Y-%m-%d %H:%M")),
            ("Revizie Document:", f"Rev.{minutes.revision} ({datetime.now().strftime('%Y-%m-%d %H:%M')})"),
            ("Participanți:", ", ".join([a.name for a in meeting.attendees]) if meeting.attendees else "Conform foii de prezență")
        ]
        for row_idx, (label, val) in enumerate(info_data):
            info_table.rows[row_idx].cells[0].paragraphs[0].add_run(label).bold = True
            info_table.rows[row_idx].cells[1].paragraphs[0].add_run(val)

        # Executive Summary
        doc.add_heading("Rezumat Executiv", level=2)
        doc.add_paragraph(minutes.summary_ro)
        if minutes.summary_en:
            p_en = doc.add_paragraph()
            r_en = p_en.add_run(f"[EN Summary] {minutes.summary_en}")
            r_en.italic = True

        # Decisions Section
        doc.add_heading("Decizii Adoptate", level=2)
        if minutes.decisions:
            dec_table = doc.add_table(rows=1, cols=3)
            dec_table.alignment = WD_TABLE_ALIGNMENT.CENTER
            hdr = dec_table.rows[0].cells
            hdr[0].paragraphs[0].add_run("Domeniu").bold = True
            hdr[1].paragraphs[0].add_run("Decizie Adoptată").bold = True
            hdr[2].paragraphs[0].add_run("Dovadă Audio (Timestamp)").bold = True

            for d in minutes.decisions:
                row = dec_table.add_row().cells
                row[0].paragraphs[0].add_run(d.topic)
                row[1].paragraphs[0].add_run(d.decision)
                ev_text = "; ".join([f"[{int(e.start)}s-{int(e.end)}s] {e.speaker or ''}: \"{e.quote[:40]}...\"" for e in d.evidence]) if d.evidence else "N/A"
                row[2].paragraphs[0].add_run(ev_text)
        else:
            doc.add_paragraph("Nicio decizie formală înregistrată.")

        # Action Items Section
        doc.add_heading("Plan de Acțiuni & Sarcini (Action Items)", level=2)
        if minutes.action_items:
            act_table = doc.add_table(rows=1, cols=4)
            act_table.alignment = WD_TABLE_ALIGNMENT.CENTER
            hdr = act_table.rows[0].cells
            hdr[0].paragraphs[0].add_run("Sarcină / Activitate").bold = True
            hdr[1].paragraphs[0].add_run("Responsabil").bold = True
            hdr[2].paragraphs[0].add_run("Termen Limită").bold = True
            hdr[3].paragraphs[0].add_run("Prioritate").bold = True

            for a in minutes.action_items:
                row = act_table.add_row().cells
                row[0].paragraphs[0].add_run(a.task)
                row[1].paragraphs[0].add_run(a.owner)
                deadline_str = a.deadline_date or a.deadline_phrase or "Nespecificat"
                row[2].paragraphs[0].add_run(deadline_str)
                row[3].paragraphs[0].add_run(a.priority.upper())
        else:
            doc.add_paragraph("Nicio sarcină de lucru identificată.")

        doc.save(str(output_path))
        logger.info(f"Generated DOCX minutes: {output_path}")
        return output_path

    def generate_pdf(self, meeting: Meeting, minutes: MinutesOfMeeting, output_path: Path) -> Path:
        """Constructs official PDF document using FPDF."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pdf = PDFReport()
        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)

        use_font = pdf.font_family_to_use
        is_unicode = use_font != "Helvetica"

        def safe_text(txt: str) -> str:
            return txt if is_unicode else self._sanitize_text(txt)

        # Title
        style_b = "" if is_unicode else "B"
        pdf.set_font(use_font, style_b, 13)
        pdf.cell(0, 8, safe_text(f"PROCES-VERBAL: {meeting.title.upper()}"), new_x="LMARGIN", new_y="NEXT", align="L")
        
        pdf.set_font(use_font, "", 10)
        pdf.cell(0, 6, safe_text(f"Data: {meeting.scheduled_at.strftime('%Y-%m-%d %H:%M')} | Tip: {meeting.meeting_type.value.upper()} | Rev.{minutes.revision}"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        # Executive Summary Section
        pdf.set_font(use_font, style_b, 11)
        pdf.set_fill_color(240, 244, 248)
        pdf.cell(190, 7, safe_text("REZUMAT EXECUTIV"), fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(use_font, "", 9)
        pdf.set_x(10)
        pdf.multi_cell(190, 5, safe_text(minutes.summary_ro), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        # Decisions
        pdf.set_font(use_font, style_b, 11)
        pdf.set_fill_color(240, 244, 248)
        pdf.cell(190, 7, safe_text(f"DECIZII ADOPTATE ({len(minutes.decisions)})"), fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(use_font, "", 9)
        if minutes.decisions:
            for i, d in enumerate(minutes.decisions, 1):
                pdf.set_font(use_font, style_b, 9)
                pdf.cell(190, 5, safe_text(f"{i}. [{d.topic}]"), new_x="LMARGIN", new_y="NEXT")
                pdf.set_font(use_font, "", 9)
                pdf.set_x(10)
                pdf.multi_cell(190, 5, safe_text(f"   {d.decision}"), new_x="LMARGIN", new_y="NEXT")
                if d.evidence:
                    pdf.set_font(use_font, "" if is_unicode else "I", 8)
                    pdf.set_text_color(90, 90, 90)
                    ev_str = f"   Audio Dovada [{int(d.evidence[0].start)}s-{int(d.evidence[0].end)}s]: \"{d.evidence[0].quote[:70]}...\""
                    pdf.set_x(10)
                    pdf.multi_cell(190, 4, safe_text(ev_str), new_x="LMARGIN", new_y="NEXT")
                    pdf.set_text_color(0, 0, 0)
                pdf.ln(2)
        else:
            pdf.cell(190, 5, safe_text("Nicio decizie formala."), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        # Action Items
        pdf.set_font(use_font, style_b, 11)
        pdf.set_fill_color(240, 244, 248)
        pdf.cell(190, 7, safe_text(f"PLAN DE ACTIUNI & SARCINI ({len(minutes.action_items)})"), fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(use_font, "", 9)
        if minutes.action_items:
            for i, a in enumerate(minutes.action_items, 1):
                pdf.set_font(use_font, style_b, 9)
                deadline_info = f" | Termen: {a.deadline_date or a.deadline_phrase or 'Nespecificat'}"
                pdf.cell(190, 5, safe_text(f"{i}. Responsabil: {a.owner}{deadline_info} [{a.priority.upper()}]"), new_x="LMARGIN", new_y="NEXT")
                pdf.set_font(use_font, "", 9)
                pdf.set_x(10)
                pdf.multi_cell(190, 5, safe_text(f"   Sarcina: {a.task}"), new_x="LMARGIN", new_y="NEXT")
                if a.evidence:
                    pdf.set_font(use_font, "" if is_unicode else "I", 8)
                    pdf.set_text_color(90, 90, 90)
                    ev_str = f"   Audio Dovada [{int(a.evidence[0].start)}s-{int(a.evidence[0].end)}s]: \"{a.evidence[0].quote[:70]}...\""
                    pdf.set_x(10)
                    pdf.multi_cell(190, 4, safe_text(ev_str), new_x="LMARGIN", new_y="NEXT")
                    pdf.set_text_color(0, 0, 0)
                pdf.ln(2)
        else:
            pdf.cell(190, 5, safe_text("Nicio sarcina de lucru."), new_x="LMARGIN", new_y="NEXT")

        pdf.output(str(output_path))
        logger.info(f"Generated PDF minutes: {output_path}")
        return output_path

    def _sanitize_text(self, text: str) -> str:
        """Replaces characters incompatible with standard latin-1 Helvetica while preserving readability."""
        replacements = {
            "ș": "s", "Ș": "S",
            "ț": "t", "Ț": "T",
            "ă": "a", "Ă": "A",
            "î": "i", "Î": "I",
            "â": "a", "Â": "A",
            "—": "-", "–": "-",
            "„": '"', "”": '"',
            "«": '"', "»": '"',
            "’": "'", "‘": "'"
        }
        res = text
        for k, v in replacements.items():
            res = res.replace(k, v)
        return res.encode("latin-1", "replace").decode("latin-1")


document_generator = DocumentGenerator()
