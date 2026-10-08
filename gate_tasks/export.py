"""The Excel test report, saved in the "data exports" folder.

A test is a task: Completed + Pass = passed, Completed + Fail = failed, To Do / In Progress = open.
The Summary numbers are formulas over the "All tests" sheet, with their values cached so previewers
that don't calculate still show them. The verdict lines are a snapshot of the export moment.
"""

import io
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

import xlsxwriter
from xlsxwriter.utility import xl_col_to_name

STALE_DAYS = 14  # an open test untouched this long is flagged as stale
FONT = "Arial"

# Theme. Results keep the same colours everywhere: a strong one for chart marks and a soft
# tint with dark text for cells. The chart colours were checked for colour-blind separation.
NAVY, INDIGO, ACCENT, TINT, LINE = "#1E1B4B", "#312E81", "#4F46E5", "#EEF2FF", "#C7D2FE"
CARD, GRID, INK, MUTED, WHITE = "#F8FAFC", "#E2E8F0", "#0F172A", "#64748B", "#FFFFFF"
RESULTS = {  # outcome: (label, chart colour, chart label ink, cell tint, cell text)
    "Passed": ("Passed", "#15803D", WHITE, "#DCFCE7", "#166534"),
    "Failed": ("Failed", "#FB7185", INK, "#FFE4E6", "#9F1239"),
    "Open": ("Open", "#6366F1", WHITE, "#E0E7FF", "#3730A3"),
    "No Need": ("No need", "#CBD5E1", INK, "#F1F5F9", "#475569"),
}
SEVERITY = {"High": ("#FFE4E6", "#9F1239"), "Medium": ("#FEF3C7", "#92400E"), "Low": ("#F1F5F9", "#475569")}
STATUSES = ("To Do", "In Progress", "No Need", "Completed")

DATA_SHEET = "All tests"
REF = f"'{DATA_SHEET}'!"  # a sheet name with a space must be quoted in formulas
DATA_HEADERS = ["ID", "Title", "Category", "Pass/Fail mark", "Status", "Outcome", "Owner", "Assigned by",
                "Deadline", "Days overdue", "Created", "Last updated", "Notes"]
COL = {name: xl_col_to_name(1 + i) for i, name in enumerate(DATA_HEADERS)}  # tables start in column B
TABLE_TOP = 4  # header row (0-based) of the table on every list sheet, under the banner
AXIS_FONT = {"name": FONT, "size": 9, "color": MUTED}


@dataclass
class Row:
    id: int
    title: str
    category: str
    mark: str
    status: str
    outcome: str
    owner: str
    source: str  # who assigned it, when that wasn't the owner
    deadline: Optional[date]
    days_overdue: Optional[int]
    created: Optional[datetime]
    updated: Optional[datetime]
    notes: str


@dataclass
class Export:
    folder: Path
    path: Path
    data: bytes


def outcome(status: str, mark: str) -> str:
    if status == "Completed":
        return "Passed" if mark == "Pass" else "Failed"
    return "No Need" if status == "No Need" else "Open"


def _date(text: str) -> Optional[date]:
    try:
        return date.fromisoformat(str(text)[:10]) if text else None
    except ValueError:
        return None


def _local(stamp: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(stamp).astimezone().replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def to_rows(tasks: list[dict], today: date) -> list[Row]:
    rows = []
    for t in tasks:
        result = outcome(t["status"], t["priority"])
        due = _date(t["deadline"])
        assigned = t.get("created_by") not in (None, t["owner_id"])
        rows.append(Row(
            id=t["id"], title=t["title"], category=(t["category"] or "").strip(), mark=t["priority"],
            status=t["status"], outcome=result, owner=t.get("owner_name") or "",
            source=(t.get("created_by_name") or "") if assigned else "", deadline=due,
            days_overdue=(today - due).days if result == "Open" and due and due < today else None,
            created=_local(t["created_at"]), updated=_local(t["updated_at"]), notes=(t["notes"] or "").strip(),
        ))
    return rows


def anomalies(rows: list[Row], today: date) -> list[tuple[str, str, Row, str]]:
    """(severity, type, row, details), most serious first."""
    found = []
    for r in rows:
        if r.outcome == "Failed":
            found.append((0, "High", "Failed test", r, "Finished with a Fail result."))
        elif r.days_overdue:
            days = f"{r.days_overdue} day{'s' if r.days_overdue != 1 else ''}"
            high = r.days_overdue >= 7
            found.append((0 if high else 1, "High" if high else "Medium", "Overdue", r,
                          f"Due {r.deadline:%Y-%m-%d}, {days} overdue."))
        elif r.outcome == "Open" and r.updated and (today - r.updated.date()).days >= STALE_DAYS:
            found.append((2, "Low", "Stale", r, f"No change for {(today - r.updated.date()).days} days."))
    found.sort(key=lambda a: (a[0], a[3].owner.lower(), a[3].id))
    return [a[1:] for a in found]


def breakdown(rows: list[Row], key: Callable[[Row], str]) -> list[dict]:
    """Counts per group, groups with finished tests first. Grouping ignores case, like Excel's "="."""
    groups: dict[str, dict] = {}
    for r in rows:
        label = key(r)
        g = groups.setdefault(label.lower(), {"label": label, "total": 0, **{name: 0 for name in RESULTS}})
        g[r.outcome] += 1
        g["total"] += 1
    return sorted(groups.values(), key=lambda g: (-(g["Passed"] + g["Failed"]), -g["total"], g["label"].lower()))


def verdict(passed: int, failed: int, overdue: int) -> tuple[str, str, str]:
    """(tone, headline, Catman's take)."""
    done = passed + failed
    late = f" {overdue} open test{'s are' if overdue != 1 else ' is'} past the deadline." if overdue else ""
    if done == 0:
        return ("none", f"Verdict: no finished tests yet.{late}",
                "Catman's take: stretching on the keyboard, waiting for the first result.")
    line = f"{passed / done:.0%} of finished tests passed ({passed} of {done}).{late}"
    if passed / done >= 0.9:
        return "good", f"Verdict: Excellent. {line}", "Catman's take: a purr-fect run. Approved."
    if passed / done >= 0.7:
        return ("fair", f"Verdict: Good, with a few failures to review. {line}",
                "Catman's take: not bad at all. He's keeping one eye open.")
    return ("poor", f"Verdict: Needs attention. {line}",
            "Catman's take: he knocked the failures off the table so they're easy to find on the Failed sheet.")


# ---------------------------------------------------------------------------------------------
# theme
# ---------------------------------------------------------------------------------------------
class _Theme:
    def __init__(self, wb: xlsxwriter.Workbook):
        self.wb = wb
        self._cache: dict[tuple, object] = {}
        self.banner = self.f(font_size=18, bold=True, font_color=WHITE, bg_color=NAVY, indent=1)
        self.stripe = self.f(bg_color=ACCENT)
        self.subtitle = self.f(font_color="#3730A3", bg_color=TINT, indent=1)
        self.section = self.f(bold=True, font_color=ACCENT, bottom=1, bottom_color=LINE)
        self.rule = self.f(bottom=1, bottom_color=LINE)
        self.th = self.f(bold=True, font_color=WHITE, bg_color=INDIGO, indent=1)
        self.th_center = self.f(bold=True, font_color=WHITE, bg_color=INDIGO, align="center")
        self.muted = self.f(font_color=MUTED, indent=1)
        self.empty = self.f(font_color=MUTED, italic=True, indent=1)
        self.band = wb.add_format({"bg_color": CARD})
        self.tint = {k: wb.add_format({"bg_color": v[3], "font_color": v[4], "bold": True}) for k, v in RESULTS.items()}
        self.severity = {k: wb.add_format({"bg_color": bg, "font_color": fg, "bold": True})
                         for k, (bg, fg) in SEVERITY.items()}

    def f(self, **props):
        """A cached format on the theme's base: Arial 10, dark ink, vertically centred."""
        key = tuple(sorted(props.items()))
        if key not in self._cache:
            self._cache[key] = self.wb.add_format({"font_name": FONT, "font_size": 10, "font_color": INK,
                                                   "valign": "vcenter", **props})
        return self._cache[key]

    def cell(self, kind: str, banded: bool = False):
        """Table body cells: text, wrap, int, pct, date or stamp."""
        props = {"bottom": 1, "bottom_color": GRID, **({"bg_color": CARD} if banded else {})}
        props.update({"text": {"indent": 1}, "wrap": {"indent": 1, "text_wrap": True},
                      "int": {"align": "center", "num_format": "0"}, "pct": {"align": "center", "num_format": "0%"},
                      "date": {"align": "center", "num_format": "yyyy-mm-dd"},
                      "stamp": {"align": "center", "num_format": "yyyy-mm-dd hh:mm"}}[kind])
        return self.f(**props)


def _banner(ws, th: _Theme, title: str, subtitle: str, last_col: int) -> None:
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 2)
    ws.set_row(0, 38)
    ws.set_row(1, 4)
    ws.set_row(2, 22)
    ws.merge_range(0, 1, 0, last_col, title, th.banner)
    ws.merge_range(1, 1, 1, last_col, "", th.stripe)
    ws.merge_range(2, 1, 2, last_col, subtitle, th.subtitle)


def _span(ws, row: int, first_col: int, last_col: int, value, fmt) -> None:
    """Merge a row range, or write the cell when the range is a single column."""
    if first_col == last_col:
        ws.write(row, first_col, value, fmt)
    else:
        ws.merge_range(row, first_col, row, last_col, value, fmt)


def _print_setup(ws, repeat_row: Optional[int] = None) -> None:
    ws.set_landscape()
    ws.set_paper(9)  # A4
    ws.fit_to_pages(1, 0)
    ws.set_margins(left=0.4, right=0.4, top=0.5, bottom=0.6)
    ws.set_footer("&L&8Gate Tasks test report&R&8Page &P of &N")
    if repeat_row is not None:
        ws.repeat_rows(repeat_row)


def _section(ws, th: _Theme, row: int, text: str, first_col: int, last_col: int) -> None:
    ws.write(row, first_col, text.upper(), th.section)
    for col in range(first_col + 1, last_col + 1):
        ws.write_blank(row, col, None, th.rule)


def _table(ws, th: _Theme, top: int, columns: list[tuple], items: list, tinted: Optional[int] = None,
           tints: Optional[dict] = None) -> int:
    """A filterable, banded table from column B. columns: (header, width, kind, getter). Returns its last row."""
    for i, (_, width, _, _) in enumerate(columns):
        if width:
            ws.set_column(1 + i, 1 + i, width)
    last = top + max(len(items), 1)
    ws.add_table(top, 1, last, len(columns), {
        "data": [[get(item) for *_, get in columns] for item in items], "style": None, "autofilter": True,
        "columns": [{"header": header, "header_format": th.th, "format": th.cell(kind)}
                    for header, _, kind, _ in columns],
    })
    ws.set_row(top, 22)
    if tinted is not None:  # colour one column's cells by value; added first so it wins over the banding
        cells = f"{xl_col_to_name(1 + tinted)}{top + 2}:{xl_col_to_name(1 + tinted)}{last + 1}"
        for value, fmt in (tints or th.tint).items():
            ws.conditional_format(cells, {"type": "cell", "criteria": "==", "value": f'"{value}"', "format": fmt})
    ws.conditional_format(f"B{top + 2}:{xl_col_to_name(len(columns))}{last + 1}",
                          {"type": "formula", "criteria": "=MOD(ROW(),2)=0", "format": th.band})
    return last


def _list_sheet(wb, th, name: str, tab: str, title: str, subtitle: str, columns: list[tuple], rows: list[Row],
                tinted: Optional[int] = None) -> None:
    ws = wb.add_worksheet(name)
    ws.set_tab_color(tab)
    _banner(ws, th, title, subtitle, len(columns))
    _table(ws, th, TABLE_TOP, columns, rows, tinted)
    ws.freeze_panes(TABLE_TOP + 1, 0)
    _print_setup(ws, TABLE_TOP)


def _chart_style(chart, title: str, width: int, height: int) -> None:
    chart.set_title({"name": title, "name_font": {"name": FONT, "size": 11, "bold": True, "color": NAVY}})
    chart.set_chartarea({"border": {"none": True}, "fill": {"color": WHITE}})
    chart.set_plotarea({"border": {"none": True}})
    chart.set_size({"width": width, "height": height})


# ---------------------------------------------------------------------------------------------
# workbook
# ---------------------------------------------------------------------------------------------
def build_workbook(rows: list[Row], *, scope_label: str, generated_by: str, now: datetime, team: bool) -> bytes:
    today = now.date()
    out = io.BytesIO()
    # User text must never turn into a formula, a number or a link.
    wb = xlsxwriter.Workbook(out, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False,
                                   "strings_to_numbers": False})
    wb.set_properties({"title": "Gate Tasks test report", "author": generated_by,
                       "comments": f"{scope_label}, exported {now:%Y-%m-%d %H:%M}"})
    th = _Theme(wb)

    first, last = TABLE_TOP + 2, TABLE_TOP + 1 + max(len(rows), 1)  # data rows on All tests (1-based)

    def rng(column: str) -> str:
        return f"{REF}${COL[column]}${first}:${COL[column]}${last}"

    count = {name: sum(r.outcome == name for r in rows) for name in RESULTS}
    overdue = sum(1 for r in rows if r.days_overdue)
    flagged = anomalies(rows, today)
    noted = [r for r in rows if r.notes]
    subtitle = (f"{scope_label}   |   {len(rows)} test{'s' if len(rows) != 1 else ''}   |   "
                f"Exported {now:%Y-%m-%d %H:%M} by {generated_by}")

    # -- Summary -------------------------------------------------------------------------------
    ws = wb.add_worksheet("Summary")
    ws.set_tab_color(NAVY)
    ws.set_column(1, 1, 24)
    ws.set_column(2, 7, 12)
    ws.set_column(8, 8, 3)
    ws.set_column(9, 16, 9.5)
    px = {1: 24, **{c: 12 for c in range(2, 8)}, 8: 3, **{c: 9.5 for c in range(9, 17)}}

    def span_px(first_col: int, last_col: int) -> int:
        return sum(int(px[c] * 7 + 5) for c in range(first_col, last_col + 1)) - 6

    chart_width = span_px(9, 16)
    _banner(ws, th, "Gate Tasks  |  Test Report", subtitle, 16)

    # Key figures as cards across the full width.
    _section(ws, th, 4, "Key figures", 1, 16)
    finished = count["Passed"] + count["Failed"]
    cards = [((1, 1), "Total tests", f"=COUNTA({rng('ID')})", len(rows), ACCENT, INK, "0", "all statuses"),
             ((2, 3), "Passed", f'=COUNTIF({rng("Outcome")},"Passed")', count["Passed"], RESULTS["Passed"][1],
              RESULTS["Passed"][4], "0", "finished with Pass"),
             ((4, 5), "Failed", f'=COUNTIF({rng("Outcome")},"Failed")', count["Failed"], RESULTS["Failed"][1],
              RESULTS["Failed"][4], "0", "finished with Fail"),
             ((6, 7), "Pass rate", "=IF(C7+E7=0,0,C7/(C7+E7))", count["Passed"] / finished if finished else 0,
              ACCENT, INK, "0%", "passed / finished"),
             ((8, 10), "Open", f'=COUNTIF({rng("Outcome")},"Open")', count["Open"], RESULTS["Open"][1],
              RESULTS["Open"][4], "0", "to do + in progress"),
             ((11, 13), "No need", f'=COUNTIF({rng("Outcome")},"No Need")', count["No Need"], "#94A3B8",
              RESULTS["No Need"][4], "0", "dropped"),
             ((14, 16), "Overdue", f'=COUNTIF({rng("Days overdue")},">0")', overdue, "#F59E0B", "#92400E", "0",
              "open and past deadline")]
    ws.set_row(5, 22)
    ws.set_row(6, 42)
    ws.set_row(7, 20)
    sides = {"left": 5, "left_color": WHITE, "right": 5, "right_color": WHITE, "bg_color": CARD, "align": "center"}
    for (c1, c2), label, formula, value, accent, ink, num, caption in cards:
        _span(ws, 5, c1, c2, label.upper(), th.f(font_size=8, bold=True, font_color=MUTED, top=5,
                                                         top_color=accent, valign="bottom", **sides))
        value_fmt = th.f(font_size=24, bold=True, font_color=ink, num_format=num, **sides)
        _span(ws, 6, c1, c2, None, value_fmt)
        ws.write_formula(6, c1, formula, value_fmt, value)
        _span(ws, 7, c1, c2, caption, th.f(font_size=8, font_color=MUTED, valign="top", bottom=1,
                                                   bottom_color=GRID, **sides))

    tone, headline, catman = verdict(count["Passed"], count["Failed"], overdue)
    edge = {"good": "#15803D", "fair": "#F59E0B", "poor": "#E11D48", "none": "#94A3B8"}[tone]
    fill = {"good": "#F0FDF4", "fair": "#FFFBEB", "poor": "#FFF1F2", "none": CARD}[tone]
    ws.set_row(9, 26)
    ws.set_row(10, 22)
    ws.merge_range(9, 1, 9, 16, headline, th.f(font_size=12, bold=True, bg_color=fill, left=5, left_color=edge,
                                               indent=1))
    ws.merge_range(10, 1, 10, 16, catman, th.f(italic=True, font_color=MUTED, bg_color=fill, left=5,
                                               left_color=edge, indent=1))

    def bar_axes(chart, values: dict) -> None:
        chart.set_y_axis({"reverse": True, "crossing": "max", "num_font": AXIS_FONT, "line": {"color": GRID},
                          "major_tick_mark": "none"})
        chart.set_x_axis({"num_font": AXIS_FONT, "line": {"none": True}, "min": 0,
                          "major_gridlines": {"visible": True, "line": {"color": GRID}}, **values})

    def results_chart(title: str, first_row: int, last_row: int):
        chart = wb.add_chart({"type": "bar", "subtype": "stacked"})
        for col, name in enumerate(RESULTS, start=3):
            _, colour, ink, _, _ = RESULTS[name]
            chart.add_series({
                "name": ["Summary", first_row - 1, col], "categories": ["Summary", first_row, 1, last_row, 1],
                "values": ["Summary", first_row, col, last_row, col], "gap": 55,
                "fill": {"color": colour}, "border": {"color": WHITE, "width": 1.5},
                "data_labels": {"value": True, "num_format": "0;-0;;",
                                "font": {"name": FONT, "size": 9, "color": ink, "bold": True}},
            })
        _chart_style(chart, title, chart_width, max(250, 110 + 36 * (last_row - first_row + 1)))
        bar_axes(chart, {"num_format": "0"})
        chart.set_legend({"position": "bottom", "font": {"name": FONT, "size": 9, "color": INK}})
        return chart

    def pass_rate_chart(title: str, first_row: int, last_row: int):
        chart = wb.add_chart({"type": "bar"})
        chart.add_series({"name": "Pass rate", "categories": ["Summary", first_row, 1, last_row, 1],
                          "values": ["Summary", first_row, 7, last_row, 7], "fill": {"color": ACCENT}, "gap": 70,
                          "data_labels": {"value": True, "num_format": "0%",
                                          "font": {"name": FONT, "size": 9, "color": INK}}})
        _chart_style(chart, title, span_px(1, 7), max(200, 90 + 30 * (last_row - first_row + 1)))
        bar_axes(chart, {"max": 1, "major_unit": 0.25, "num_format": "0%"})
        chart.set_legend({"none": True})
        return chart

    def rows_for(pixels: int) -> int:  # Summary data rows are 20 px tall
        return math.ceil(pixels / 20) + 1

    def header_row(row: int, labels: list[str], count_rows: int) -> None:
        ws.set_row(row, 22)
        ws.write(row, 1, labels[0], th.th)
        for i, text in enumerate(labels[1:], start=2):
            ws.write(row, i, text, th.th_center)
        for n in range(count_rows):
            ws.set_row(row + 1 + n, 20)

    # Tests by status: amounts and shares.
    top = 12
    _section(ws, th, top, "Tests by status", 1, 16)
    header_row(top + 1, ["Status", "Tests", "Share"], len(STATUSES))
    for n, status in enumerate(STATUSES):
        r, banded = top + 2 + n, n % 2 == 1
        value = sum(row.status == status for row in rows)
        ws.write_string(r, 1, status, th.cell("text", banded))
        ws.write_formula(r, 2, f'=COUNTIF({rng("Status")},"{status}")', th.cell("int", banded), value)
        ws.write_formula(r, 3, f"=IF($B$7=0,0,C{r + 1}/$B$7)", th.cell("pct", banded),
                         value / len(rows) if rows else 0)
    ws.conditional_format(top + 2, 3, top + 5, 3, {"type": "data_bar", "bar_color": LINE, "bar_solid": True,
                                                  "min_type": "num", "min_value": 0, "max_type": "num", "max_value": 1})
    if rows:  # an all-zero chart says nothing
        status_chart = wb.add_chart({"type": "column"})
        status_chart.add_series({"name": "Tests", "categories": ["Summary", top + 2, 1, top + 5, 1],
                                 "values": ["Summary", top + 2, 2, top + 5, 2], "fill": {"color": ACCENT}, "gap": 110,
                                 "data_labels": {"value": True,
                                                 "font": {"name": FONT, "size": 9, "color": INK, "bold": True}}})
        _chart_style(status_chart, "Tests by status", span_px(5, 16), 230)
        status_chart.set_x_axis({"num_font": AXIS_FONT, "line": {"color": GRID}, "major_tick_mark": "none"})
        status_chart.set_y_axis({"num_font": AXIS_FONT, "num_format": "0", "min": 0, "line": {"none": True},
                                 "major_gridlines": {"visible": True, "line": {"color": GRID}}})
        status_chart.set_legend({"none": True})
        ws.insert_chart(top + 1, 5, status_chart, {"x_offset": 6, "y_offset": 2})
    top += 1 + max(6, rows_for(230) if rows else 0) + 1
    page_breaks = []

    def group_section(top: int, noun: str, groups: list[dict], column: str, empty_label: str) -> int:
        page_breaks.append(top)
        _section(ws, th, top, f"Results by {noun}", 1, 16)
        hdr = top + 1
        header_row(hdr, [noun.capitalize(), "Tests", "Passed", "Failed", "Open", "No need", "Pass rate"], len(groups))
        for n, g in enumerate(groups):
            r, banded = hdr + 1 + n, n % 2 == 1
            ws.write_string(r, 1, g["label"] or empty_label, th.cell("text", banded))
            match = f'--({rng(column)}={f"$B${r + 1}" if g["label"] else chr(34) * 2})'
            ws.write_formula(r, 2, f"=SUMPRODUCT({match})", th.cell("int", banded), g["total"])
            for col, name in enumerate(RESULTS, start=3):
                ws.write_formula(r, col, f'=SUMPRODUCT({match},--({rng("Outcome")}="{name}"))',
                                 th.cell("int", banded), g[name])
            done = g["Passed"] + g["Failed"]
            ws.write_formula(r, 7, f'=IF(D{r + 1}+E{r + 1}=0,"-",D{r + 1}/(D{r + 1}+E{r + 1}))',
                             th.cell("pct", banded), g["Passed"] / done if done else "-")
        first_row, last_row = hdr + 1, hdr + len(groups)
        ws.conditional_format(first_row, 7, last_row, 7, {"type": "data_bar", "bar_color": "#BBF7D0", "bar_solid": True,
                                                          "min_type": "num", "min_value": 0,
                                                          "max_type": "num", "max_value": 1})
        counts = results_chart(f"Results by {noun}", first_row, last_row)
        ws.insert_chart(top + 1, 9, counts, {"x_offset": 2, "y_offset": 2})
        left = len(groups) + 1
        rated = sum(1 for g in groups if g["Passed"] + g["Failed"])  # sorted, so the rated ones come first
        if rated >= 2:
            rate = pass_rate_chart(f"Pass rate by {noun} (finished tests)", first_row, first_row + rated - 1)
            ws.insert_chart(last_row + 2, 1, rate, {"x_offset": 2, "y_offset": 2})
            left += 1 + rows_for(rate.height)
        return top + 1 + max(left, rows_for(counts.height)) + 1

    # Breakdowns only when they say something: two or more categories / people.
    categories = breakdown(rows, lambda r: r.category)
    if len(categories) >= 2:
        top = group_section(top, "category", categories, "Category", "(no category)")
    people = breakdown(rows, lambda r: r.owner)
    if team and len(people) >= 2:
        top = group_section(top, "person", people, "Owner", "(unknown)")

    ws.set_h_pagebreaks(page_breaks)
    _section(ws, th, top, "How to read this report", 1, 16)
    for n, line in enumerate([
        "Passed / Failed: finished (Completed) tests with a Pass / Fail result. Pass rate = passed / finished.",
        "Open: To Do or In Progress. No need: tests that were dropped.",
        "Overdue: open tests whose deadline was before the export date. Tests without a deadline are never overdue.",
        f"Stale: open tests with no change for {STALE_DAYS} days or more.",
        f"The numbers on this sheet are formulas over the '{DATA_SHEET}' sheet. The verdict is a snapshot of the export.",
    ]):
        ws.merge_range(top + 1 + n, 1, top + 1 + n, 16, line, th.muted)
    _print_setup(ws)

    # -- one sheet per outcome (only the ones that have tests) -----------------------------
    owner = [("Owner", 18, "text", lambda r: r.owner)] if team else []
    base = [("ID", 7, "int", lambda r: r.id), ("Title", 40, "wrap", lambda r: r.title),
            ("Category", 16, "text", lambda r: r.category)]
    tail = [("Assigned by", 16, "text", lambda r: r.source), ("Deadline", 13, "date", lambda r: r.deadline),
            ("Last updated", 17, "stamp", lambda r: r.updated), ("Notes", 60, "wrap", lambda r: r.notes)]
    open_cols = (base + [("Status", 13, "text", lambda r: r.status), ("Pass/Fail mark", 14, "text", lambda r: r.mark)]
                 + owner + tail[:2] + [("Days overdue", 13, "int", lambda r: r.days_overdue)] + tail[2:])
    for name, title, note, columns in [
        ("Passed", "Passed tests", "Finished tests with a Pass result. Nice work.", base + owner + tail),
        ("Failed", "Failed tests", "Finished tests with a Fail result. Their notes are the place to start.",
         base + owner + tail),
        ("Open", "Open tests", "To Do and In Progress, most overdue first.", open_cols),
        ("No Need", "No need", "Tests that were dropped.", base + owner + tail),
    ]:
        selected = [r for r in rows if r.outcome == name]
        if name == "Open":
            selected.sort(key=lambda r: (-(r.days_overdue or 0), r.deadline or date.max, r.id))
        if selected:
            _list_sheet(wb, th, name, RESULTS[name][1], f"{title}  |  {len(selected)}",
                        f"{note}   |   {subtitle}", columns, selected)

    # -- notes & anomalies ------------------------------------------------------------------------
    ws = wb.add_worksheet("Notes & anomalies")
    ws.set_tab_color("#F59E0B")
    width = 9 if team else 8
    _banner(ws, th, "Notes & anomalies", f"Failed tests, overdue tests (High after 7 days) and open tests unchanged "
                                         f"for {STALE_DAYS}+ days, then every note   |   {subtitle}", width)
    # Both tables share one column layout, so titles and notes get the wide columns.
    for i, w in enumerate([11, 15, 7, 36] + ([18] if team else []) + [16, 13, 30, 56]):
        ws.set_column(1 + i, 1 + i, w)
    who = [("Owner", 0, "text", lambda r: r.owner)] if team else []
    top = TABLE_TOP
    _section(ws, th, top, f"Anomalies ({len(flagged)})", 1, width)
    if flagged:
        cols = ([("Severity", 0, "text", lambda a: a[0]), ("Type", 0, "text", lambda a: a[1]),
                 ("ID", 0, "int", lambda a: a[2].id), ("Title", 0, "wrap", lambda a: a[2].title)]
                + [(h, w, k, lambda a, g=g: g(a[2])) for h, w, k, g in who]
                + [("Category", 0, "text", lambda a: a[2].category), ("Deadline", 0, "date", lambda a: a[2].deadline),
                   ("Details", 0, "wrap", lambda a: a[3]), ("Notes", 0, "wrap", lambda a: a[2].notes)])
        top = _table(ws, th, top + 1, cols, flagged, tinted=0, tints=th.severity) + 2
    else:
        ws.write(top + 1, 1, "None. No failed tests, nothing overdue, nothing stale.", th.empty)
        top += 3
    _section(ws, th, top, f"Notes log ({len(noted)})", 1, width)
    if noted:
        cols = ([("Outcome", 0, "text", lambda r: r.outcome), ("Status", 0, "text", lambda r: r.status),
                 ("ID", 0, "int", lambda r: r.id), ("Title", 0, "wrap", lambda r: r.title)] + who
                + [("Category", 0, "text", lambda r: r.category), ("Deadline", 0, "date", lambda r: r.deadline),
                   ("Last updated", 0, "stamp", lambda r: r.updated), ("Notes", 0, "wrap", lambda r: r.notes)])
        _table(ws, th, top + 1, cols, noted, tinted=0)
    else:
        ws.write(top + 1, 1, "No notes written yet.", th.empty)
    _print_setup(ws)

    # -- all tests: the data the Summary formulas read ---------------------------------------------
    widths = [7, 40, 16, 14, 13, 11, 18, 16, 13, 13, 17, 17, 60]
    kinds = ["int", "wrap", "text", "text", "text", "text", "text", "text", "date", "int", "stamp", "stamp", "wrap"]
    getters = [lambda r: r.id, lambda r: r.title, lambda r: r.category, lambda r: r.mark, lambda r: r.status,
               lambda r: r.outcome, lambda r: r.owner, lambda r: r.source, lambda r: r.deadline,
               lambda r: r.days_overdue, lambda r: r.created, lambda r: r.updated, lambda r: r.notes]
    _list_sheet(wb, th, DATA_SHEET, INDIGO, "All tests", f"Every test in one table   |   {subtitle}",
                list(zip(DATA_HEADERS, widths, kinds, getters)), rows, tinted=DATA_HEADERS.index("Outcome"))

    wb.close()
    return out.getvalue()


def save_report(folder: Path, tasks: list[dict], *, scope_label: str, scope_slug: str, generated_by: str,
                team: bool, now: Optional[datetime] = None) -> Export:
    """Write the report into folder, creating the folder if needed."""
    now = now or datetime.now()
    folder.mkdir(parents=True, exist_ok=True)
    base = f"Gate Tasks report - {scope_slug} - {now:%Y-%m-%d %H-%M-%S}"
    stem, n = base, 2
    while (folder / f"{stem}.xlsx").exists():
        stem, n = f"{base} ({n})", n + 1
    data = build_workbook(to_rows(tasks, now.date()), scope_label=scope_label, generated_by=generated_by,
                          now=now, team=team)
    path = folder / f"{stem}.xlsx"
    path.write_bytes(data)
    return Export(folder=folder, path=path, data=data)
