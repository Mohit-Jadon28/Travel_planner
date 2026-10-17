
from __future__ import annotations

from collections import defaultdict
from typing import Any

from fpdf import FPDF


class TravelPDF(FPDF):
    def header(self):
        self.set_fill_color(24, 60, 92)
        self.rect(0, 0, self.w, 18, style="F")
        self.set_y(4)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", style="B", size=13)
        self.cell(0, 10, "Travel Plan", align="L")
        self.set_text_color(0, 0, 0)
        self.ln(16)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", size=8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")
        self.set_text_color(0, 0, 0)


def _latin1(s: str) -> str:
    return (s or "").encode("latin-1", "replace").decode("latin-1")


def _content_width(pdf: "TravelPDF") -> float:
    return pdf.w - pdf.l_margin - pdf.r_margin


def _render_budget_table(pdf: "TravelPDF", budget: dict[str, Any], currency: str):
    pdf.add_page()
    pdf.set_font("Helvetica", style="B", size=14)
    pdf.multi_cell(0, 10, "Budget Breakdown", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    rows = [
        ("Flight", budget.get("flight", 0)), ("Hotel", budget.get("hotel", 0)),
        ("Food", budget.get("food", 0)), ("Transport", budget.get("transport", 0)),
        ("Activities", budget.get("activities", 0)), ("Buffer", budget.get("buffer", 0)),
        ("Total", budget.get("total", 0)), ("Budget", budget.get("budget", 0)),
        ("Remaining", budget.get("remaining", 0)),
    ]
    if budget.get("display_currency"):
        rows.append((f"Total ({budget['display_currency']})", budget.get("total_in_display_currency", 0)))

    col_w = (100, 60)
    pdf.set_font("Helvetica", style="B", size=11)
    pdf.set_fill_color(230, 236, 242)
    pdf.cell(col_w[0], 8, "Item", border=1, fill=True)
    pdf.cell(col_w[1], 8, _latin1(f"Amount ({currency})"), border=1, fill=True, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", size=11)
    for label, amount in rows:
        try:
            amount_str = f"{float(amount):,.0f}"
        except (TypeError, ValueError):
            amount_str = str(amount)
        pdf.cell(col_w[0], 8, _latin1(label), border=1)
        pdf.cell(col_w[1], 8, _latin1(amount_str), border=1, new_x="LMARGIN", new_y="NEXT")

    if budget.get("recommendations"):
        pdf.ln(6)
        pdf.set_font("Helvetica", style="B", size=12)
        pdf.cell(0, 8, "Recommendations", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        for rec in budget["recommendations"]:
            pdf.multi_cell(
                _content_width(pdf), 6, _latin1(f"- {rec}"),
                new_x="LMARGIN", new_y="NEXT",
            )


def _render_markdown_body(pdf: "TravelPDF", markdown_text: str):
    pdf.add_page()
    for raw_line in markdown_text.splitlines():
        line = raw_line.rstrip()
        if not line:
            pdf.ln(3)
            continue
        if line.startswith("# "):
            pdf.set_font("Helvetica", style="B", size=15)
            pdf.set_text_color(24, 60, 92)
            pdf.ln(4)
            pdf.multi_cell(0, 9, _latin1(line[2:].strip()), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
        elif line.startswith("## "):
            pdf.set_font("Helvetica", style="B", size=12)
            pdf.multi_cell(0, 7, _latin1(line[3:].strip()), new_x="LMARGIN", new_y="NEXT")
        elif line.startswith(("- ", "* ")):
            pdf.set_font("Helvetica", size=10)
            pdf.multi_cell(0, 6, _latin1("  \u2022 " + line[2:].strip()), new_x="LMARGIN", new_y="NEXT")
        elif line.startswith("|"):
            pdf.set_font("Courier", size=8)
            pdf.multi_cell(0, 5, _latin1(line), new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font("Helvetica", size=10)
            pdf.multi_cell(0, 6, _latin1(line), new_x="LMARGIN", new_y="NEXT")


def markdown_plan_to_pdf(plan_text: str, budget_result: dict[str, Any], request: dict[str, Any],
                          resource_usage: list[dict[str, Any]], warnings: list[str],
                          out_path: str = "travel_plan.pdf") -> str:
    pdf = TravelPDF()
    pdf.set_auto_page_break(auto=True, margin=18)

    _render_markdown_body(pdf, plan_text)

    if budget_result:
        _render_budget_table(pdf, budget_result, request.get("currency", ""))

    if warnings:
        pdf.add_page()
        pdf.set_font("Helvetica", style="B", size=13)
        pdf.cell(0, 10, "Guardrail Notes", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        for w in warnings:
            pdf.multi_cell(
                _content_width(pdf), 6, _latin1(f"- {w}"),
                new_x="LMARGIN", new_y="NEXT",
            )

    if resource_usage:
        pdf.add_page()
        pdf.set_font("Helvetica", style="B", size=13)
        pdf.cell(0, 10, "Run Efficiency Summary", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Courier", size=9)
        totals = defaultdict(lambda: {"tool_calls": 0, "llm_calls": 0, "tokens": 0})
        for u in resource_usage:
            totals[u["agent"]]["tool_calls"] += u.get("tool_calls_used", 0)
            totals[u["agent"]]["llm_calls"] += u.get("llm_calls_used", 0)
            totals[u["agent"]]["tokens"] += u.get("total_tokens", 0)

        available_content_width = pdf.w - pdf.l_margin - pdf.r_margin
        for agent, t in totals.items():
            pdf.multi_cell(
                available_content_width, 5,
                _latin1(f"{agent:12s} tool_calls={t['tool_calls']} llm_calls={t['llm_calls']} tokens={t['tokens']}"),
            )

    pdf.output(out_path)
    return out_path
