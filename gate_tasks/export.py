"""The Excel test report, styled like the app: dark panels, the app's colours, charts and highlights.

A test is a task: Completed + Pass = passed, Completed + Fail = failed, To Do / In Progress = open.
Every number on the Summary is a formula over the "All tests" sheet, with its value cached so
previewers that don't calculate still show it. The verdict and highlights are a snapshot.
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
FONT = "Segoe UI"  # Windows' interface font: the closest match to the app's Inter on any office PC

# The app's palette (static/css/app.css): night-sky canvas, glass panels, indigo and purple accents.
CANVAS, PANEL, PANEL_ALT, EDGE = "#0F1022", "#181B33", "#1E2240", "#2A2F55"
TEXT, SOFT, MUTED = "#F1F5F9", "#CBD5E1", "#94A3B8"
HEADER, HEADER_TEXT, ACCENT, SKY, AMBER = "#312E81", "#E0E7FF", "#A5B4FC", "#38BDF8", "#FBBF24"
GRADIENT = ["#6366F1", "#A855F7"]  # the app's primary button
# Gradient angles: XlsxWriter treats 0 as "unset" (90, top to bottom), so left-to-right fills use
# 180 degrees with the colours reversed.
STATUS_COLOURS = {"To Do": "#F43F5E", "In Progress": "#F59E0B", "No Need": "#8B5CF6", "Completed": "#10B981"}
STATUSES = tuple(STATUS_COLOURS)
# outcome: (label, chart colour, chart label ink, pill fill, pill text). Checked for colour-blind
# separation on the dark panels; labels and the tables carry the values too.
RESULTS = {
    "Passed": ("Passed", "#34D399", "#052E1C", "#064E3B", "#6EE7B7"),
    "Failed": ("Failed", "#F43F5E", "#FFFFFF", "#4C0519", "#FDA4AF"),
    "Open": ("Open", "#6366F1", "#FFFFFF", "#272A6B", "#C7D2FE"),
    "No Need": ("No need", "#64748B", "#FFFFFF", "#1F2937", "#CBD5E1"),
}
SEVERITY = {"High": ("#4C0519", "#FDA4AF"), "Medium": ("#451A03", "#FCD34D"), "Low": ("#1F2937", "#CBD5E1")}

DATA_SHEET, CHART_SHEET = "All tests", "Chart data"
REF = f"'{DATA_SHEET}'!"  # a sheet name with a space must be quoted in formulas
DATA_HEADERS = ["ID", "Title", "Category", "Pass/Fail mark", "Status", "Outcome", "Owner", "Assigned by",
                "Deadline", "Days overdue", "Created", "Last updated", "Notes"]
COL = {name: xl_col_to_name(1 + i) for i, name in enumerate(DATA_HEADERS)}  # tables start in column B
TABLE_TOP = 4  # header row (0-based) of the table on every list sheet, under the banner


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


# ---------------------------------------------------------------------------------------------
# the numbers
# ---------------------------------------------------------------------------------------------
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
        g = groups.setdefault(label.lower(), {"label": label, "total": 0, "overdue": 0, **{n: 0 for n in RESULTS}})
        g[r.outcome] += 1
        g["total"] += 1
        g["overdue"] += 1 if r.days_overdue else 0
    return sorted(groups.values(), key=lambda g: (-(g["Passed"] + g["Failed"]), -g["total"], g["label"].lower()))


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def verdict(passed: int, failed: int, overdue: int) -> tuple[str, str, str]:
    """(tone, headline, Catman's take)."""
    done = passed + failed
    late = f" {_plural(overdue, 'open test')} past the deadline." if overdue else ""
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


def highlights(rows: list[Row], categories: list[dict], people: list[dict], team: bool,
               today: date) -> list[tuple[str, str, str]]:
    """Short, readable facts worth a look: (label, sentence, colour)."""
    found = []
    rated = [g for g in categories if g["Passed"] + g["Failed"] and g["label"]]
    if len(rated) >= 2:
        best = max(rated, key=lambda g: (g["Passed"] / (g["Passed"] + g["Failed"]), g["Passed"] + g["Failed"]))
        done = best["Passed"] + best["Failed"]
        found.append(("Strongest category", f"{best['label']}: {best['Passed'] / done:.0%} passed "
                                            f"({best['Passed']} of {done}).", RESULTS["Passed"][1]))
    worst = max(categories, key=lambda g: g["Failed"], default=None)
    if worst and worst["Failed"] and worst["label"]:
        found.append(("Most failures", f"{worst['label']}: {_plural(worst['Failed'], 'failed test')}. "
                                       f"Start with the Failed sheet.", "#FB7185"))
    if team and len(people) >= 2:
        busiest = max(people, key=lambda g: g["total"])
        found.append(("Busiest board", f"{busiest['label']}: {_plural(busiest['total'], 'test')}, "
                                       f"{busiest['Open']} still open.", ACCENT))
    late = max((r for r in rows if r.days_overdue), key=lambda r: r.days_overdue, default=None)
    if late:
        found.append(("Longest overdue", f'"{late.title}" is {_plural(late.days_overdue, "day")} late.', AMBER))
    waiting = [r for r in rows if r.outcome == "Open" and r.created and r is not late]
    oldest = min(waiting, key=lambda r: r.created, default=None)
    if oldest and (today - oldest.created.date()).days >= 1:
        found.append(("Waiting the longest", f'"{oldest.title}" has been open for '
                                             f'{_plural((today - oldest.created.date()).days, "day")}.', SKY))
    undated = sum(1 for r in rows if r.outcome == "Open" and not r.deadline)
    if undated:
        found.append(("No deadline", f"{_plural(undated, 'open test')} without a deadline. "
                                     f"They are never counted as overdue.", MUTED))
    if not found:
        found.append(("All quiet", "Nothing stands out yet. Add tests, finish a few and export again.", ACCENT))
    return found[:6]


# ---------------------------------------------------------------------------------------------
# look and feel
# ---------------------------------------------------------------------------------------------
class _Theme:
    def __init__(self, wb: xlsxwriter.Workbook):
        self.wb = wb
        self._cache: dict[tuple, object] = {}
        self.canvas = self.f()
        self.subtitle = self.f(font_color=MUTED, indent=1)
        self.section = self.f(font_size=11, bold=True, font_color=ACCENT, bottom=1, bottom_color=EDGE)
        self.rule = self.f(bottom=1, bottom_color=EDGE)
        self.th = self.f(bold=True, font_color=HEADER_TEXT, bg_color=HEADER, indent=1)
        self.th_center = self.f(bold=True, font_color=HEADER_TEXT, bg_color=HEADER, align="center")
        self.muted = self.f(font_color=MUTED, indent=1)
        self.empty = self.f(font_color=MUTED, italic=True, indent=1)
        self.band = wb.add_format({"bg_color": PANEL_ALT})
        self.pill = {k: wb.add_format({"bg_color": v[3], "font_color": v[4], "bold": True}) for k, v in RESULTS.items()}
        self.severity = {k: wb.add_format({"bg_color": bg, "font_color": fg, "bold": True})
                         for k, (bg, fg) in SEVERITY.items()}

    def f(self, **props):
        """A cached format on the dark base: Segoe UI 10, light ink on the canvas, vertically centred."""
        key = tuple(sorted(props.items()))
        if key not in self._cache:
            self._cache[key] = self.wb.add_format({"font_name": FONT, "font_size": 10, "font_color": TEXT,
                                                   "bg_color": CANVAS, "valign": "vcenter", **props})
        return self._cache[key]

    def font(self, **props):
        """A font-only format, for the parts of a rich string."""
        return self.f(**props)

    def cell(self, kind: str, banded: bool = False):
        """Table cells on a panel: text, strong, wrap, id, int, pct, date or stamp."""
        props = {"bg_color": PANEL_ALT if banded else PANEL, "bottom": 1, "bottom_color": EDGE}
        props.update({
            "text": {"indent": 1}, "strong": {"indent": 1, "bold": True, "text_wrap": True},
            "wrap": {"indent": 1, "text_wrap": True, "font_color": SOFT},
            "id": {"align": "center", "font_color": MUTED}, "int": {"align": "center", "num_format": "0"},
            "late": {"align": "center", "num_format": "0", "bold": True, "font_color": AMBER},
            "pct": {"align": "center", "num_format": "0%", "bold": True},
            "date": {"align": "center", "num_format": "yyyy-mm-dd", "font_color": SOFT},
            "stamp": {"align": "center", "num_format": "yyyy-mm-dd hh:mm", "font_color": SOFT},
        }[kind])
        return self.f(**props)


def _px(width: float) -> int:
    return int(width * 7 + 5)


def _paint(ws, th: _Theme, widths: dict[int, float], upto: int = 30) -> None:
    """A dark page: every column gets the canvas colour, so empty space matches the app."""
    ws.hide_gridlines(2)
    for col in range(upto + 1):
        ws.set_column(col, col, widths.get(col, 9), th.canvas)


def _banner(ws, th: _Theme, title: str, subtitle: str, width: int) -> None:
    """The app's purple gradient bar with the title, and a quiet subtitle line under it."""
    ws.set_row(0, 26)
    ws.set_row(1, 26)
    ws.set_row(2, 22)
    ws.insert_textbox(0, 1, title, {
        "width": width, "height": 58, "y_offset": 6, "object_position": 3,
        "font": {"name": FONT, "size": 20, "bold": True, "color": "#FFFFFF"},
        "align": {"vertical": "middle", "horizontal": "left"},
        "gradient": {"colors": GRADIENT, "angle": 45}, "line": {"none": True},
    })
    ws.write(2, 1, subtitle, th.subtitle)


def _span(ws, row: int, first_col: int, last_col: int, value, fmt, last_row: Optional[int] = None) -> None:
    """Merge a range, or write the cell when the range is a single cell."""
    if first_col == last_col and (last_row is None or last_row == row):
        ws.write(row, first_col, value, fmt)
    else:
        ws.merge_range(row, first_col, last_row if last_row is not None else row, last_col, value, fmt)


def _section(ws, th: _Theme, row: int, text: str, first_col: int, last_col: int) -> None:
    ws.set_row(row, 24)
    ws.write(row, first_col, text.upper(), th.section)
    for col in range(first_col + 1, last_col + 1):
        ws.write_blank(row, col, None, th.rule)


def _print_setup(ws, repeat_row: Optional[int] = None) -> None:
    ws.set_landscape()
    ws.set_paper(9)  # A4
    ws.fit_to_pages(1, 0)
    ws.set_margins(left=0.3, right=0.3, top=0.4, bottom=0.5)
    ws.set_footer("&L&8Gate Tasks test report&R&8Page &P of &N")
    if repeat_row is not None:
        ws.repeat_rows(repeat_row)


def _table(ws, th: _Theme, top: int, columns: list[tuple], items: list, pill_col: Optional[int] = None,
           pills: Optional[dict] = None) -> int:
    """A filterable, banded table from column B. columns: (header, width, kind, getter). Returns its last row."""
    last = top + max(len(items), 1)
    ws.add_table(top, 1, last, len(columns), {
        "data": [[get(item) for *_, get in columns] for item in items], "style": None, "autofilter": True,
        "columns": [{"header": header, "header_format": th.th, "format": th.cell(kind)}
                    for header, _, kind, _ in columns],
    })
    ws.set_row(top, 24)
    if pill_col is not None:  # colour one column like the app's badges; added first so it wins over the banding
        cells = f"{xl_col_to_name(1 + pill_col)}{top + 2}:{xl_col_to_name(1 + pill_col)}{last + 1}"
        for value, fmt in (pills or th.pill).items():
            ws.conditional_format(cells, {"type": "cell", "criteria": "==", "value": f'"{value}"', "format": fmt})
    ws.conditional_format(f"B{top + 2}:{xl_col_to_name(len(columns))}{last + 1}",
                          {"type": "formula", "criteria": "=MOD(ROW(),2)=1", "format": th.band})
    return last


def _list_sheet(wb, th: _Theme, name: str, tab: str, title: str, subtitle: str, columns: list[tuple],
                rows: list[Row], pill_col: Optional[int] = None) -> None:
    ws = wb.add_worksheet(name)
    ws.set_tab_color(tab)
    _paint(ws, th, {0: 2.5, **{1 + i: c[1] for i, c in enumerate(columns)}}, upto=max(30, len(columns) + 6))
    _banner(ws, th, title, subtitle, sum(_px(c[1]) for c in columns))
    _table(ws, th, TABLE_TOP, columns, rows, pill_col)
    ws.freeze_panes(TABLE_TOP + 1, 0)
    _print_setup(ws, TABLE_TOP)


def _dark_chart(chart, title: str, width: int, height: int, legend: Optional[str] = None) -> None:
    chart.set_title({"name": title, "name_font": {"name": FONT, "size": 11, "bold": True, "color": TEXT}})
    chart.set_chartarea({"border": {"color": EDGE}, "fill": {"color": PANEL}})
    chart.set_plotarea({"border": {"none": True}, "fill": {"none": True}})
    chart.set_size({"width": width, "height": height})
    if legend:
        chart.set_legend({"position": legend, "font": {"name": FONT, "size": 9, "color": SOFT}})
    else:
        chart.set_legend({"none": True})


AXIS = {"num_font": {"name": FONT, "size": 9, "color": MUTED}, "line": {"color": EDGE}, "major_tick_mark": "none"}
HIDDEN_AXIS = {"visible": False, "major_gridlines": {"visible": False}}


def _label_font(colour: str) -> dict:
    return {"name": FONT, "size": 9, "bold": True, "color": colour}


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
    by_status = {s: sum(r.status == s for r in rows) for s in STATUSES}
    finished = count["Passed"] + count["Failed"]
    overdue = sum(1 for r in rows if r.days_overdue)
    flagged = anomalies(rows, today)
    noted = [r for r in rows if r.notes]
    categories = breakdown(rows, lambda r: r.category)
    people = breakdown(rows, lambda r: r.owner)
    subtitle = (f"{scope_label}   |   {_plural(len(rows), 'test')}   |   "
                f"Exported {now:%Y-%m-%d %H:%M} by {generated_by}")

    # -- Summary: a dashboard like the app -----------------------------------------------------
    ws = wb.add_worksheet("Summary")
    ws.set_tab_color(GRADIENT[0])
    grid = 10.5  # twelve equal columns, B to M
    _paint(ws, th, {0: 2.5, **{c: grid for c in range(1, 13)}, 13: 2.5})

    def span_px(first_col: int, last_col: int) -> int:
        return (last_col - first_col + 1) * _px(grid)

    def rows_for(pixels: int) -> int:  # rows on this sheet are 20 px unless set otherwise
        return math.ceil(pixels / 20) + 1

    _banner(ws, th, "Gate Tasks  |  Test Report", subtitle, span_px(1, 12))
    ws.set_row(3, 8)

    # Key figures as cards, coloured like the app's stats.
    cards = [(1, "Total tests", f"=COUNTA({rng('ID')})", len(rows), ACCENT, "0", "all statuses"),
             (3, "Passed", f'=COUNTIF({rng("Outcome")},"Passed")', count["Passed"], RESULTS["Passed"][1], "0",
              "finished with Pass"),
             (5, "Failed", f'=COUNTIF({rng("Outcome")},"Failed")', count["Failed"], "#FB7185", "0",
              "finished with Fail"),
             (7, "Pass rate", "=IF(D6+F6=0,0,D6/(D6+F6))", count["Passed"] / finished if finished else 0, SKY,
              "0%", "passed / finished"),
             (9, "Open", f'=COUNTIF({rng("Outcome")},"Open")', count["Open"], "#818CF8", "0", "to do + in progress"),
             (11, "Overdue", f'=COUNTIF({rng("Days overdue")},">0")', overdue, AMBER, "0", "open, past the deadline")]
    ws.set_row(4, 22)
    ws.set_row(5, 46)
    ws.set_row(6, 22)
    sides = {"bg_color": PANEL, "align": "center", "left": 5, "left_color": CANVAS, "right": 5, "right_color": CANVAS}
    for c, label, formula, value, colour, num, caption in cards:
        ws.merge_range(4, c, 4, c + 1, label.upper(), th.f(font_size=8, bold=True, font_color=MUTED, top=5,
                                                           top_color=colour, valign="bottom", **sides))
        value_fmt = th.f(font_size=26, bold=True, font_color=colour, num_format=num, **sides)
        ws.merge_range(5, c, 5, c + 1, None, value_fmt)
        ws.write_formula(5, c, formula, value_fmt, value)
        ws.merge_range(6, c, 6, c + 1, caption, th.f(font_size=8, font_color=MUTED, valign="top", **sides))

    # The verdict, tinted by how it went.
    tone, headline, catman = verdict(count["Passed"], count["Failed"], overdue)
    edge, fill = {"good": ("#34D399", "#0B2A20"), "fair": (AMBER, "#2A2108"), "poor": ("#FB7185", "#2D0B16"),
                  "none": ("#64748B", PANEL)}[tone]
    ws.set_row(7, 12)
    ws.set_row(8, 30)
    ws.set_row(9, 24)
    ws.merge_range(8, 1, 8, 12, headline, th.f(font_size=12, bold=True, bg_color=fill, left=5, left_color=edge,
                                               indent=1))
    ws.merge_range(9, 1, 9, 12, catman, th.f(italic=True, font_color=SOFT, bg_color=fill, left=5, left_color=edge,
                                             indent=1))
    ws.set_row(10, 14)

    # Hidden helper cells the three "at a glance" charts read.
    cd = wb.add_worksheet(CHART_SHEET)
    cd.write_row(0, 0, ["Status", "Tests"])
    for n, status in enumerate(STATUSES, start=1):
        cd.write(n, 0, status)
        cd.write_formula(n, 1, f'=COUNTIF({rng("Status")},"{status}")', None, by_status[status])
    cd.write_row(6, 0, ["", "Passed", "Failed"])
    cd.write(7, 0, "Finished tests")
    cd.write_formula(7, 1, "=Summary!D6", None, count["Passed"])
    cd.write_formula(7, 2, "=Summary!F6", None, count["Failed"])
    completion = by_status["Completed"] / len(rows) if rows else 0
    cd.write_row(9, 0, ["", "Completed", "Remaining"])
    cd.write(10, 0, "All tests")
    cd.write_formula(10, 1, '=IF(Summary!B6=0,0,B5/Summary!B6)', None, completion)
    cd.write_formula(10, 2, "=1-B11", None, 1 - completion)
    cd.hide()

    top = 11
    _section(ws, th, top, "At a glance", 1, 12)
    glance_h = 230
    blocks = [(1, 4), (5, 8), (9, 12)]
    if rows:
        donut = wb.add_chart({"type": "doughnut"})
        donut.add_series({
            "name": "Tests", "categories": [CHART_SHEET, 1, 0, 4, 0], "values": [CHART_SHEET, 1, 1, 4, 1],
            "points": [{"fill": {"color": STATUS_COLOURS[s]}, "border": {"color": PANEL, "width": 2.25}}
                       for s in STATUSES],
            "data_labels": {"percentage": True, "num_format": "0%;;;", "font": _label_font("#FFFFFF")},
        })
        donut.set_hole_size(58)
        _dark_chart(donut, "Task distribution", span_px(1, 4) - 8, glance_h, legend="right")
        ws.insert_chart(top + 1, 1, donut, {"x_offset": 4, "y_offset": 6})

        meter = wb.add_chart({"type": "bar", "subtype": "percent_stacked"})
        meter.add_series({"name": "Completed", "categories": [CHART_SHEET, 10, 0, 10, 0],
                          "values": [CHART_SHEET, 10, 1, 10, 1], "gap": 110, "border": {"none": True},
                          "gradient": {"colors": [STATUS_COLOURS["Completed"], STATUS_COLOURS["To Do"]], "angle": 180},
                          "data_labels": {"value": True, "num_format": "0%;;;", "font": _label_font("#FFFFFF")}})
        meter.add_series({"name": "Remaining", "categories": [CHART_SHEET, 10, 0, 10, 0],
                          "values": [CHART_SHEET, 10, 2, 10, 2], "fill": {"color": EDGE}, "border": {"none": True}})
        _dark_chart(meter, "Completion score", span_px(9, 12) - 8, glance_h)
        meter.set_x_axis(HIDDEN_AXIS)
        meter.set_y_axis(HIDDEN_AXIS)
        ws.insert_chart(top + 1, 9, meter, {"x_offset": 4, "y_offset": 6})

    if finished:
        split = wb.add_chart({"type": "bar", "subtype": "percent_stacked"})
        for col, name in ((1, "Passed"), (2, "Failed")):
            _, colour, ink, _, _ = RESULTS[name]
            split.add_series({
                "name": [CHART_SHEET, 6, col], "categories": [CHART_SHEET, 7, 0, 7, 0],
                "values": [CHART_SHEET, 7, col, 7, col], "fill": {"color": colour}, "gap": 110,
                "border": {"color": PANEL, "width": 2.25},
                "data_labels": ({"series_name": True, "value": True, "separator": " ", "font": _label_font(ink)}
                                if count[name] else None),
            })
        _dark_chart(split, "Pass / fail split", span_px(5, 8) - 8, glance_h)
        split.set_x_axis(HIDDEN_AXIS)
        split.set_y_axis(HIDDEN_AXIS)
        ws.insert_chart(top + 1, 5, split, {"x_offset": 4, "y_offset": 6})

    below = top + 1 + rows_for(glance_h + 6)
    empty_panel = th.f(font_color=MUTED, italic=True, bg_color=PANEL, align="center", border=1, border_color=EDGE)
    if not rows:
        ws.merge_range(top + 1, 1, below - 1, 12, "No tests to chart yet. Add a few and export again.", empty_panel)
    elif not finished:
        ws.merge_range(top + 1, 5, below - 1, 8, "No finished tests yet", empty_panel)
    # A big, live caption under each chart.
    ws.set_row(below, 28)
    caption = th.f(font_size=12, bold=True, align="center")
    ws.merge_range(below, 1, below, 4, None, caption)
    ws.write_formula(below, 1, '=B6&IF(B6=1," test"," tests")&" on the board"', th.f(font_size=12, bold=True,
                     align="center", font_color=ACCENT), f"{_plural(len(rows), 'test')} on the board")
    ws.merge_range(below, 5, below, 8, None, caption)
    ws.write_formula(below, 5, '=IF(D6+F6=0,"No finished tests yet",TEXT(H6,"0%")&" of finished tests passed")',
                     th.f(font_size=12, bold=True, align="center", font_color=RESULTS["Passed"][1]),
                     f"{count['Passed'] / finished:.0%} of finished tests passed" if finished else "No finished tests yet")
    ws.merge_range(below, 9, below, 12, None, caption)
    ws.write_formula(below, 9, f"=TEXT('{CHART_SHEET}'!B11,\"0%\")&\" of all tests completed\"",
                     th.f(font_size=12, bold=True, align="center", font_color=SKY),
                     f"{completion:.0%} of all tests completed")

    # Highlights: the story in a few lines.
    top = below + 2
    _section(ws, th, top, "Highlights", 1, 12)
    row = top + 1
    for label, sentence, colour in highlights(rows, categories, people, team, today):
        ws.set_row(row, 26)
        line = th.f(bg_color=PANEL, left=5, left_color=colour, indent=1)
        ws.merge_range(row, 1, row, 12, None, line)
        ws.write_rich_string(row, 1, th.font(bold=True, font_color=colour, bg_color=PANEL), f"{label}   ",
                             th.font(font_color=TEXT, bg_color=PANEL), sentence, line)
        ws.set_row(row + 1, 5)
        row += 2

    page_breaks = []

    def group_section(top: int, noun: str, groups: list[dict], column: str, empty_label: str) -> int:
        page_breaks.append(top)
        _section(ws, th, top, f"Results by {noun}", 1, 12)
        hdr = top + 1
        ws.set_row(hdr, 24)
        for c1, c2, text in [(1, 4, noun.capitalize()), (5, 5, "Tests"), (6, 6, "Passed"), (7, 7, "Failed"),
                             (8, 8, "Open"), (9, 9, "No need"), (10, 10, "Overdue"), (11, 12, "Pass rate")]:
            _span(ws, hdr, c1, c2, text, th.th if c1 == 1 else th.th_center)
        for n, g in enumerate(groups):
            r, banded = hdr + 1 + n, n % 2 == 1
            ws.set_row(r, 22)
            _span(ws, r, 1, 4, g["label"] or empty_label, th.cell("strong", banded))
            match = f'--({rng(column)}={f"$B${r + 1}" if g["label"] else chr(34) * 2})'
            ws.write_formula(r, 5, f"=SUMPRODUCT({match})", th.cell("int", banded), g["total"])
            for col, name in enumerate(RESULTS, start=6):
                ws.write_formula(r, col, f'=SUMPRODUCT({match},--({rng("Outcome")}="{name}"))',
                                 th.cell("int", banded), g[name])
            ws.write_formula(r, 10, f'=SUMPRODUCT({match},--({rng("Days overdue")}>0))', th.cell("int", banded),
                             g["overdue"])
            done = g["Passed"] + g["Failed"]
            ws.merge_range(r, 11, r, 12, None, th.cell("pct", banded))
            ws.write_formula(r, 11, f'=IF(G{r + 1}+H{r + 1}=0,"-",G{r + 1}/(G{r + 1}+H{r + 1}))',
                             th.cell("pct", banded), g["Passed"] / done if done else "-")
        first_row, last_row = hdr + 1, hdr + len(groups)
        # Pass rates read like a traffic light: green from 90%, amber from 70%, red below.
        cell = f"L{first_row + 1}"
        for rule, colour in ((f"{cell}>=0.9", RESULTS["Passed"][1]), (f"{cell}>=0.7", AMBER), (f"{cell}<0.7", "#FB7185")):
            ws.conditional_format(first_row, 11, last_row, 11, {
                "type": "formula", "criteria": f"=AND(ISNUMBER({cell}),{rule})", "stop_if_true": True,
                "format": wb.add_format({"font_color": colour, "bold": True})})

        chart_row = last_row + 2
        height = max(220, 110 + 34 * len(groups))
        rated = sum(1 for g in groups if g["Passed"] + g["Failed"])  # sorted, so the rated ones come first
        counts = wb.add_chart({"type": "bar", "subtype": "stacked"})
        for col, name in enumerate(RESULTS, start=6):
            _, colour, ink, _, _ = RESULTS[name]
            counts.add_series({
                "name": ["Summary", hdr, col], "categories": ["Summary", first_row, 1, last_row, 1],
                "values": ["Summary", first_row, col, last_row, col], "gap": 50,
                "fill": {"color": colour}, "border": {"color": PANEL, "width": 1.5},
                "data_labels": {"value": True, "num_format": "0;-0;;", "font": _label_font(ink)},
            })
        _dark_chart(counts, f"Results by {noun}", span_px(1, 6 if rated >= 2 else 12) - 8, height, legend="bottom")
        counts.set_y_axis({**AXIS, "reverse": True, "crossing": "max"})
        counts.set_x_axis({**AXIS, "num_format": "0", "min": 0, "line": {"none": True},
                           "major_gridlines": {"visible": True, "line": {"color": EDGE}}})
        ws.insert_chart(chart_row, 1, counts, {"x_offset": 4, "y_offset": 2})
        if rated >= 2:
            rate = wb.add_chart({"type": "bar"})
            rate.add_series({"name": "Pass rate", "categories": ["Summary", first_row, 1, first_row + rated - 1, 1],
                             "values": ["Summary", first_row, 11, first_row + rated - 1, 11], "gap": 60,
                             "gradient": {"colors": GRADIENT[::-1], "angle": 180}, "border": {"none": True},
                             "data_labels": {"value": True, "num_format": "0%", "font": _label_font(TEXT)}})
            _dark_chart(rate, f"Pass rate by {noun} (finished tests)", span_px(7, 12) - 8, height)
            rate.set_y_axis({**AXIS, "reverse": True, "crossing": "max"})
            rate.set_x_axis({**AXIS, "min": 0, "max": 1, "major_unit": 0.25, "num_format": "0%", "line": {"none": True},
                             "major_gridlines": {"visible": True, "line": {"color": EDGE}}})
            ws.insert_chart(chart_row, 7, rate, {"x_offset": 4, "y_offset": 2})
        return chart_row + rows_for(height) + 1

    # Breakdowns only when they say something: two or more categories / people.
    top = row + 1
    if len(categories) >= 2:
        top = group_section(top, "category", categories, "Category", "(no category)")
    if team and len(people) >= 2:
        top = group_section(top, "person", people, "Owner", "(unknown)")
    ws.set_h_pagebreaks(page_breaks)

    _section(ws, th, top, "How to read this report", 1, 12)
    for n, line in enumerate([
        "Passed / Failed: finished (Completed) tests with a Pass / Fail result. Pass rate = passed / finished.",
        "Open: To Do or In Progress. No need: tests that were dropped.",
        "Overdue: open tests whose deadline was before the export date. Tests without a deadline are never overdue.",
        f"Stale: open tests with no change for {STALE_DAYS} days or more.",
        f"Every number on this sheet is a formula over the '{DATA_SHEET}' sheet. The verdict and highlights "
        f"are a snapshot of the export.",
    ]):
        ws.merge_range(top + 1 + n, 1, top + 1 + n, 12, line, th.muted)
    ws.merge_range(top + 7, 1, top + 7, 12, "Made with Gate Tasks. Catman approved.",
                   th.f(font_size=8, italic=True, font_color=EDGE, align="right"))
    _print_setup(ws)
    ws.activate()

    # -- one sheet per outcome (only the ones that have tests) -----------------------------
    owner = [("Owner", 18, "text", lambda r: r.owner)] if team else []
    base = [("ID", 7, "id", lambda r: r.id), ("Title", 40, "strong", lambda r: r.title),
            ("Category", 16, "text", lambda r: r.category)]
    tail = [("Assigned by", 16, "text", lambda r: r.source), ("Deadline", 13, "date", lambda r: r.deadline),
            ("Last updated", 17, "stamp", lambda r: r.updated), ("Notes", 60, "wrap", lambda r: r.notes)]
    open_cols = (base + [("Status", 13, "text", lambda r: r.status), ("Pass/Fail mark", 14, "text", lambda r: r.mark)]
                 + owner + tail[:2] + [("Days overdue", 13, "late", lambda r: r.days_overdue)] + tail[2:])
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
    ws.set_tab_color(AMBER)
    widths = [11, 15, 7, 36] + ([18] if team else []) + [16, 13, 30, 56]
    _paint(ws, th, {0: 2.5, **{1 + i: w for i, w in enumerate(widths)}})
    _banner(ws, th, "Notes & anomalies", f"Failed, overdue and stale tests, then every note   |   {subtitle}",
            sum(_px(w) for w in widths))
    who = [("Owner", 0, "text", lambda r: r.owner)] if team else []
    top = TABLE_TOP
    _section(ws, th, top, f"Anomalies ({len(flagged)})", 1, len(widths))
    ws.write(top + 1, 1, f"High: failed, or more than 7 days overdue. Medium: overdue. Low: open and unchanged for "
                         f"{STALE_DAYS}+ days.", th.muted)
    if flagged:
        cols = ([("Severity", 0, "text", lambda a: a[0]), ("Type", 0, "text", lambda a: a[1]),
                 ("ID", 0, "id", lambda a: a[2].id), ("Title", 0, "strong", lambda a: a[2].title)]
                + [(h, w, k, lambda a, g=g: g(a[2])) for h, w, k, g in who]
                + [("Category", 0, "text", lambda a: a[2].category), ("Deadline", 0, "date", lambda a: a[2].deadline),
                   ("Details", 0, "wrap", lambda a: a[3]), ("Notes", 0, "wrap", lambda a: a[2].notes)])
        top = _table(ws, th, top + 2, cols, flagged, pill_col=0, pills=th.severity) + 2
    else:
        ws.write(top + 2, 1, "None. No failed tests, nothing overdue, nothing stale. Catman is impressed.", th.empty)
        top += 4
    _section(ws, th, top, f"Notes log ({len(noted)})", 1, len(widths))
    if noted:
        cols = ([("Outcome", 0, "text", lambda r: r.outcome), ("Status", 0, "text", lambda r: r.status),
                 ("ID", 0, "id", lambda r: r.id), ("Title", 0, "strong", lambda r: r.title)] + who
                + [("Category", 0, "text", lambda r: r.category), ("Deadline", 0, "date", lambda r: r.deadline),
                   ("Last updated", 0, "stamp", lambda r: r.updated), ("Notes", 0, "wrap", lambda r: r.notes)])
        _table(ws, th, top + 1, cols, noted, pill_col=0)
    else:
        ws.write(top + 1, 1, "No notes written yet.", th.empty)
    _print_setup(ws)

    # -- all tests: the data every Summary formula reads -------------------------------------------
    widths = [7, 40, 16, 14, 13, 11, 18, 16, 13, 13, 17, 17, 60]
    kinds = ["id", "strong", "text", "text", "text", "text", "text", "text", "date", "late", "stamp", "stamp", "wrap"]
    getters = [lambda r: r.id, lambda r: r.title, lambda r: r.category, lambda r: r.mark, lambda r: r.status,
               lambda r: r.outcome, lambda r: r.owner, lambda r: r.source, lambda r: r.deadline,
               lambda r: r.days_overdue, lambda r: r.created, lambda r: r.updated, lambda r: r.notes]
    _list_sheet(wb, th, DATA_SHEET, HEADER, "All tests", f"Every test in one table   |   {subtitle}",
                list(zip(DATA_HEADERS, widths, kinds, getters)), rows, pill_col=DATA_HEADERS.index("Outcome"))

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
