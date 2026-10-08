"""Excel and CSV reports of the test results, saved in the "data exports" folder.

A test is a task: Completed + Pass = passed, Completed + Fail = failed, To Do / In Progress = open.
The Summary sheet's numbers are formulas over the "All tests" sheet (with their values cached, so
previewers that don't calculate still show them); the commentary lines are a snapshot.
"""

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

import xlsxwriter

STALE_DAYS = 14  # an open test untouched for this long is flagged as stale
FONT = "Arial"

# Results use the reserved status colours and always carry a label; everything else stays neutral.
GOOD, CRITICAL, OPEN_GREY, SKIP_GREY, ACCENT = "#0CA30C", "#D03B3B", "#94A3B8", "#CBD5E1", "#4F46E5"
INK, MUTED, PANEL, HEAD, GRID = "#1E1B4B", "#64748B", "#F1F5F9", "#312E81", "#E2E8F0"

DATA_SHEET = "All tests"
REF = f"'{DATA_SHEET}'!"  # a sheet name with a space must be quoted in formulas
DATA_HEADERS = ["ID", "Title", "Category", "Pass/Fail mark", "Status", "Outcome", "Owner", "From",
                "Deadline", "Days overdue", "Created", "Last updated", "Notes"]
COL = {name: chr(ord("A") + i) for i, name in enumerate(DATA_HEADERS)}
STATUSES = ("To Do", "In Progress", "No Need", "Completed")
RESULTS = (("Passed", "✅ Passed", GOOD, "#FFFFFF"), ("Failed", "❌ Failed", CRITICAL, "#FFFFFF"),
           ("Open", "⏳ Open", OPEN_GREY, INK), ("No Need", "🚫 No need", SKIP_GREY, INK))


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
    xlsx: Path
    csv: Path
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
        late = (today - due).days if result == "Open" and due and due < today else None
        assigned = t.get("created_by") not in (None, t["owner_id"])
        rows.append(Row(
            id=t["id"], title=t["title"], category=(t["category"] or "").strip(), mark=t["priority"],
            status=t["status"], outcome=result, owner=t.get("owner_name") or "", deadline=due,
            source=(t.get("created_by_name") or "") if assigned else "", days_overdue=late,
            created=_local(t["created_at"]), updated=_local(t["updated_at"]), notes=(t["notes"] or "").strip(),
        ))
    return rows


def anomalies(rows: list[Row], today: date) -> list[tuple[str, str, Row, str]]:
    """(severity, type, row, detail), most serious first."""
    found = []
    for r in rows:
        if r.outcome == "Failed":
            found.append((0, "High", "❌ Failed test", r, "Finished with a Fail result."))
        elif r.days_overdue:
            days = f"{r.days_overdue} day{'s' if r.days_overdue != 1 else ''}"
            found.append((0 if r.days_overdue >= 7 else 1, "High" if r.days_overdue >= 7 else "Medium",
                          "⏰ Overdue", r, f"Due {r.deadline:%Y-%m-%d}, {days} overdue."))
        elif r.outcome == "Open" and r.updated and (today - r.updated.date()).days >= STALE_DAYS:
            found.append((2, "Low", "🧊 Stale", r, f"No change for {(today - r.updated.date()).days} days."))
    found.sort(key=lambda a: (a[0], a[3].owner.lower(), a[3].id))
    return [a[1:] for a in found]


def breakdown(rows: list[Row], key: Callable[[Row], str]) -> list[dict]:
    """Counts per group. Grouping ignores case, like Excel's "=" in the formulas that check it."""
    groups: dict[str, dict] = {}
    for r in rows:
        label = key(r)
        g = groups.setdefault(label.lower(), {"label": label, "total": 0, **{name: 0 for name, *_ in RESULTS}})
        g[r.outcome] += 1
        g["total"] += 1
    return sorted(groups.values(), key=lambda g: (-(g["Passed"] + g["Failed"]), -g["total"], g["label"].lower()))


def verdict(passed: int, failed: int) -> tuple[str, str]:
    done = passed + failed
    if done == 0:
        return "⚪ No finished tests yet.", "🐱 Catman's take: stretching and waiting for the first result."
    rate = passed / done
    line = f"{rate:.0%} of finished tests passed ({passed} of {done})."
    if rate >= 0.9:
        return f"🟢 Excellent: {line}", "🐱 Catman's take: purr-fect run. Approved."
    if rate >= 0.7:
        return f"🟡 Good, with a few failures to look into: {line}", "🐱 Catman's take: not bad! He's keeping one eye open."
    return (f"🔴 Needs attention: {line}",
            "🐱 Catman's take: he knocked the failures off the table so they're easy to find on the Failed sheet.")


# ---------------------------------------------------------------------------------------------
# workbook
# ---------------------------------------------------------------------------------------------
class _Formats:
    def __init__(self, wb: xlsxwriter.Workbook):
        def f(**props):
            return wb.add_format({"font_name": FONT, "font_size": 10, "valign": "top", **props})
        self.text = f()
        self.wrap = f(text_wrap=True)
        self.date = f(num_format="yyyy-mm-dd", align="left")
        self.stamp = f(num_format="yyyy-mm-dd hh:mm", align="left")
        self.int = f(num_format="0", align="center")
        self.title = f(font_size=20, bold=True, font_color=INK, valign="vcenter")
        self.h2 = f(font_size=16, bold=True, font_color=INK, valign="vcenter")
        self.muted = f(font_color=MUTED)
        self.muted_i = f(font_color=MUTED, italic=True)
        self.section = f(font_size=12, bold=True, font_color=HEAD, bottom=2, bottom_color=HEAD)
        self.verdict = f(font_size=12, bold=True, font_color=INK)
        self.tile_label = f(font_size=9, font_color=MUTED, bg_color=PANEL, top=2, top_color=ACCENT, align="center")
        self.tile = f(font_size=20, bold=True, font_color=INK, bg_color=PANEL, align="center", valign="vcenter", num_format="0")
        self.tile_pct = f(font_size=20, bold=True, font_color=INK, bg_color=PANEL, align="center", valign="vcenter", num_format="0%")
        self.th = f(bold=True, font_color="#FFFFFF", bg_color=HEAD, valign="vcenter")
        self.cell = f(num_format="0", align="center")
        self.pct = f(num_format="0%", align="center")
        self.high = f(bg_color="#FDE2E2", font_color="#9B1C1C", bold=True)
        self.medium = f(bg_color="#FEF3C7", font_color="#92400E", bold=True)
        self.low = f(bg_color=PANEL, font_color=MUTED, bold=True)


def _axis_font() -> dict:
    return {"name": FONT, "size": 9, "color": MUTED}


def _style(chart, title: str, width: int = 520, height: int = 300) -> None:
    chart.set_title({"name": title, "name_font": {"name": FONT, "size": 11, "bold": True, "color": INK}})
    chart.set_chartarea({"border": {"none": True}})
    chart.set_plotarea({"border": {"none": True}})
    chart.set_size({"width": width, "height": height})


def _table(ws, top: int, left: int, columns: list[tuple], rows: list[Row], fm: _Formats) -> None:
    """columns: (header, width, format, getter)."""
    for i, (_, width, *_rest) in enumerate(columns):
        ws.set_column(left + i, left + i, width)
    data = [[get(r) for *_, get in columns] for r in rows]
    ws.add_table(top, left, top + max(len(rows), 1), left + len(columns) - 1, {
        "data": data, "style": "Table Style Light 1", "autofilter": True,
        "columns": [{"header": header, "header_format": fm.th, "format": fmt} for header, _, fmt, _ in columns],
    })


def _list_sheet(wb, fm, name: str, tab: str, title: str, note: str, columns: list[tuple], rows: list[Row]) -> None:
    ws = wb.add_worksheet(name)
    ws.set_tab_color(tab)
    ws.set_row(0, 26)
    ws.write(0, 0, title, fm.h2)
    ws.write(1, 0, note, fm.muted)
    _table(ws, 3, 0, columns, rows, fm)
    ws.freeze_panes(4, 0)
    ws.set_landscape()
    ws.fit_to_pages(1, 0)


def build_workbook(rows: list[Row], *, scope_label: str, generated_by: str, now: datetime, team: bool) -> bytes:
    today = now.date()
    out = io.BytesIO()
    # User text must never turn into a formula or a link.
    wb = xlsxwriter.Workbook(out, {"in_memory": True, "strings_to_formulas": False, "strings_to_urls": False,
                                   "strings_to_numbers": False})
    wb.set_properties({"title": "Gate Tasks test report", "author": generated_by,
                       "comments": f"{scope_label}, exported {now:%Y-%m-%d %H:%M}"})
    fm = _Formats(wb)

    last = max(len(rows), 1) + 1  # last data row on the All tests sheet (1-based)

    def rng(column: str) -> str:
        return f"{REF}${COL[column]}$2:${COL[column]}${last}"

    count = {name: sum(r.outcome == name for r in rows) for name, *_ in RESULTS}
    overdue = sum(1 for r in rows if r.days_overdue)
    flagged = anomalies(rows, today)
    noted = [r for r in rows if r.notes]

    # -- Summary -------------------------------------------------------------------------------
    ws = wb.add_worksheet("Summary")
    ws.set_tab_color(ACCENT)
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 2)
    ws.set_column(1, 1, 24)
    ws.set_column(2, 7, 13)
    ws.set_column(8, 8, 3)
    ws.set_row(0, 34)
    ws.write(0, 1, "📊 Gate Tasks — Test report", fm.title)
    ws.write(1, 1, f"{scope_label} · {len(rows)} test{'s' if len(rows) != 1 else ''} · exported "
                   f"{now:%Y-%m-%d %H:%M} by {generated_by} · a snapshot of that moment", fm.muted)

    tiles = [("🧪 Total tests", f"=COUNTA({rng('ID')})", len(rows)),
             ("✅ Passed", f'=COUNTIF({rng("Outcome")},"Passed")', count["Passed"]),
             ("❌ Failed", f'=COUNTIF({rng("Outcome")},"Failed")', count["Failed"]),
             ("🎯 Pass rate", "=IF(C5+D5=0,0,C5/(C5+D5))",
              count["Passed"] / (count["Passed"] + count["Failed"]) if count["Passed"] + count["Failed"] else 0),
             ("⏳ Open", f'=COUNTIF({rng("Outcome")},"Open")', count["Open"]),
             ("🚫 No need", f'=COUNTIF({rng("Outcome")},"No Need")', count["No Need"]),
             ("⏰ Overdue", f'=COUNTIF({rng("Days overdue")},">0")', overdue)]
    ws.set_row(4, 40)
    for i, (label, formula, value) in enumerate(tiles):
        ws.write(3, 1 + i, label, fm.tile_label)
        ws.write_formula(4, 1 + i, formula, fm.tile_pct if label.endswith("Pass rate") else fm.tile, value)
    ws.conditional_format("E5", {"type": "data_bar", "bar_color": GOOD, "bar_solid": True,
                                 "min_type": "num", "min_value": 0, "max_type": "num", "max_value": 1})

    headline, catman = verdict(count["Passed"], count["Failed"])
    ws.write(6, 1, headline, fm.verdict)
    ws.write(7, 1, catman, fm.muted_i)
    if flagged:
        ws.write(8, 1, f"⚠️ {len(flagged)} anomal{'ies' if len(flagged) != 1 else 'y'} to look at "
                       f"(failed, overdue or stale): see the Notes & anomalies sheet.", fm.text)

    def results_chart(title: str, first: int, last_row: int):
        chart = wb.add_chart({"type": "bar", "subtype": "stacked"})
        for col, (name, label, colour, ink) in enumerate(RESULTS, start=3):
            chart.add_series({
                "name": ["Summary", first - 1, col], "categories": ["Summary", first, 1, last_row, 1],
                "values": ["Summary", first, col, last_row, col], "gap": 60,
                "fill": {"color": colour}, "border": {"color": "#FFFFFF", "width": 1.25},
                "data_labels": {"value": True, "num_format": "0;-0;;", "font": {"name": FONT, "size": 9, "color": ink}},
            })
        _style(chart, title, height=max(240, 90 + 34 * (last_row - first + 1)))
        chart.set_y_axis({"reverse": True, "crossing": "max", "num_font": _axis_font(), "line": {"color": "#CBD5E1"}})
        chart.set_x_axis({"num_font": _axis_font(), "num_format": "0", "min": 0, "line": {"none": True},
                          "major_gridlines": {"visible": True, "line": {"color": GRID}}})
        chart.set_legend({"position": "bottom", "font": {"name": FONT, "size": 9, "color": INK}})
        return chart

    def group_section(top: int, heading: str, groups: list[dict], column: str, empty_label: str) -> int:
        ws.write(top, 1, heading, fm.section)
        hdr = top + 1
        for i, text in enumerate(["Tests", "✅ Passed", "❌ Failed", "⏳ Open", "🚫 No need", "Pass rate"]):
            ws.write(hdr, 2 + i, text, fm.th)
        ws.write(hdr, 1, heading.split(" ", 1)[1].capitalize(), fm.th)
        for n, g in enumerate(groups):
            r = hdr + 1 + n
            label = g["label"] or empty_label
            ws.write_string(r, 1, label, fm.text)
            match = f'--({rng(column)}={"$B$%d" % (r + 1) if g["label"] else chr(34) * 2})'
            ws.write_formula(r, 2, f"=SUMPRODUCT({match})", fm.cell, g["total"])
            for col, (name, *_rest) in enumerate(RESULTS, start=3):
                ws.write_formula(r, col, f'=SUMPRODUCT({match},--({rng("Outcome")}="{name}"))', fm.cell, g[name])
            done = g["Passed"] + g["Failed"]
            ws.write_formula(r, 7, f'=IF(D{r + 1}+E{r + 1}=0,"—",D{r + 1}/(D{r + 1}+E{r + 1}))', fm.pct,
                             g["Passed"] / done if done else "—")
        first, last_row = hdr + 1, hdr + len(groups)
        counts = results_chart(f"Results by {heading.split(' ', 1)[1].lower()}", first, last_row)
        ws.insert_chart(top, 9, counts, {"x_offset": 4})
        height = counts.height
        rated = sum(1 for g in groups if g["Passed"] + g["Failed"])  # groups are sorted: rated ones first
        if rated >= 2:
            rate = wb.add_chart({"type": "bar"})
            rate.add_series({"name": "Pass rate", "categories": ["Summary", first, 1, first + rated - 1, 1],
                             "values": ["Summary", first, 7, first + rated - 1, 7], "fill": {"color": ACCENT},
                             "gap": 80, "data_labels": {"value": True, "num_format": "0%",
                                                        "font": {"name": FONT, "size": 9, "color": INK}}})
            _style(rate, f"Pass rate by {heading.split(' ', 1)[1].lower()} (finished tests)",
                   height=max(220, 80 + 30 * rated))
            rate.set_y_axis({"reverse": True, "crossing": "max", "num_font": _axis_font(), "line": {"color": "#CBD5E1"}})
            rate.set_x_axis({"min": 0, "max": 1, "num_format": "0%", "num_font": _axis_font(), "line": {"none": True},
                             "major_gridlines": {"visible": True, "line": {"color": GRID}}})
            rate.set_legend({"none": True})
            ws.insert_chart(top + height // 20 + 1, 9, rate, {"x_offset": 4})
            height += rate.height + 20
        return top + max(len(groups) + 3, height // 20 + 2)

    # Tests by status: amounts and shares.
    top = 10
    ws.write(top, 1, "Tests by status", fm.section)
    for i, text in enumerate(["Status", "Tests", "Share"]):
        ws.write(top + 1, 1 + i, text, fm.th)
    for n, status in enumerate(STATUSES):
        r = top + 2 + n
        value = sum(row.status == status for row in rows)
        ws.write_string(r, 1, status, fm.text)
        ws.write_formula(r, 2, f'=COUNTIF({rng("Status")},"{status}")', fm.cell, value)
        ws.write_formula(r, 3, f"=IF($B$5=0,0,C{r + 1}/$B$5)", fm.pct, value / len(rows) if rows else 0)
    status_chart = wb.add_chart({"type": "column"})
    status_chart.add_series({"name": "Tests", "categories": ["Summary", top + 2, 1, top + 5, 1],
                             "values": ["Summary", top + 2, 2, top + 5, 2], "fill": {"color": ACCENT}, "gap": 90,
                             "data_labels": {"value": True, "font": {"name": FONT, "size": 9, "color": INK}}})
    _style(status_chart, "Tests by status")
    status_chart.set_x_axis({"num_font": _axis_font(), "line": {"color": "#CBD5E1"}})
    status_chart.set_y_axis({"num_font": _axis_font(), "num_format": "0", "min": 0, "line": {"none": True},
                             "major_gridlines": {"visible": True, "line": {"color": GRID}}})
    status_chart.set_legend({"none": True})
    ws.insert_chart(top, 9, status_chart, {"x_offset": 4})
    top += max(8, status_chart.height // 20 + 2)

    # Breakdowns only when they say something: two or more categories / people.
    categories = breakdown(rows, lambda r: r.category)
    if len(categories) >= 2:
        top = group_section(top, "By category", categories, "Category", "(no category)")
    people = breakdown(rows, lambda r: r.owner)
    if team and len(people) >= 2:
        top = group_section(top, "By person", people, "Owner", "(unknown)")

    ws.write(top, 1, "How to read this report", fm.section)
    for n, line in enumerate([
        "✅ Passed / ❌ Failed: finished (Completed) tests with a Pass / Fail result. Pass rate = passed ÷ finished.",
        "⏳ Open: To Do or In Progress.  🚫 No need: tests that were dropped.",
        "⏰ Overdue: open tests whose deadline was before the export date. Tests without a deadline are never overdue.",
        f"🧊 Stale: open tests with no change for {STALE_DAYS} days or more.",
        f"The numbers on this sheet are formulas over the '{DATA_SHEET}' sheet; the verdict lines are a snapshot.",
    ]):
        ws.write(top + 1 + n, 1, line, fm.muted)
    ws.set_landscape()
    ws.fit_to_pages(1, 0)

    # -- one sheet per result (only the ones that have tests) ------------------------------
    owner = [("Owner", 18, fm.text, lambda r: r.owner)] if team else []
    base = [("ID", 7, fm.int, lambda r: r.id), ("Title", 38, fm.wrap, lambda r: r.title),
            ("Category", 16, fm.text, lambda r: r.category)]
    tail = [("From", 16, fm.text, lambda r: r.source), ("Deadline", 12, fm.date, lambda r: r.deadline),
            ("Last updated", 17, fm.stamp, lambda r: r.updated), ("Notes", 60, fm.wrap, lambda r: r.notes)]
    sheets = [
        ("Passed", GOOD, "✅ Passed tests", "Finished tests with a Pass result. Nice work.", base + owner + tail),
        ("Failed", CRITICAL, "❌ Failed tests", "Finished tests with a Fail result. Their notes are the place to start.",
         base + owner + tail),
        ("Open", OPEN_GREY, "⏳ Open tests", "To Do and In Progress, most overdue first.",
         base + [("Status", 13, fm.text, lambda r: r.status), ("Pass/Fail mark", 13, fm.text, lambda r: r.mark)]
         + owner + tail[:2] + [("Days overdue", 13, fm.int, lambda r: r.days_overdue)] + tail[2:]),
        ("No need", SKIP_GREY, "🚫 No need", "Tests that were dropped.", base + owner + tail),
    ]
    for name, tab, title, note, columns in sheets:
        selected = [r for r in rows if r.outcome == ("No Need" if name == "No need" else name)]
        if name == "Open":
            selected.sort(key=lambda r: (-(r.days_overdue or 0), r.deadline or date.max, r.id))
        if selected:
            _list_sheet(wb, fm, name, tab, f"{title} — {len(selected)}", note, columns, selected)

    # -- notes & anomalies ------------------------------------------------------------------------
    ws = wb.add_worksheet("Notes & anomalies")
    ws.set_tab_color("#F59E0B")
    ws.set_row(0, 26)
    ws.write(0, 0, "⚠️ Notes & anomalies", fm.h2)
    ws.write(1, 0, f"Anomalies: failed tests, overdue tests (High after 7 days) and open tests unchanged for "
                   f"{STALE_DAYS}+ days. Overdue is counted from the export date.", fm.muted)
    widths = [10, 16, 7, 34] + ([18] if team else []) + [14, 12, 30, 50]
    for i, width in enumerate(widths):
        ws.set_column(i, i, width)
    top = 3
    ws.write(top, 0, f"Anomalies ({len(flagged)})", fm.section)
    if flagged:
        headers = ["Severity", "Type", "ID", "Title"] + (["Owner"] if team else []) + ["Category", "Deadline", "Details", "Notes"]
        data = [[sev, kind, r.id, r.title] + ([r.owner] if team else []) + [r.category, r.deadline, detail, r.notes]
                for sev, kind, r, detail in flagged]
        formats = [fm.text, fm.text, fm.int, fm.wrap] + ([fm.text] if team else []) + [fm.text, fm.date, fm.wrap, fm.wrap]
        ws.add_table(top + 1, 0, top + 1 + len(data), len(headers) - 1, {
            "data": data, "style": "Table Style Light 1", "autofilter": True,
            "columns": [{"header": h, "header_format": fm.th, "format": f} for h, f in zip(headers, formats)]})
        span = f"A{top + 3}:A{top + 2 + len(data)}"
        for level, fmt in (("High", fm.high), ("Medium", fm.medium), ("Low", fm.low)):
            ws.conditional_format(span, {"type": "cell", "criteria": "==", "value": f'"{level}"', "format": fmt})
        top += len(data) + 3
    else:
        ws.write(top + 1, 0, "🎉 None: no failed tests, nothing overdue, nothing stale.", fm.text)
        top += 3
    ws.write(top, 0, f"📝 Notes log ({len(noted)})", fm.section)
    if noted:
        # Same column layout as the anomalies table above, so titles and notes get the wide columns.
        headers = ["Outcome", "Status", "ID", "Title"] + (["Owner"] if team else []) + ["Category", "Deadline", "Last updated", "Notes"]
        data = [[r.outcome, r.status, r.id, r.title] + ([r.owner] if team else []) + [r.category, r.deadline, r.updated, r.notes]
                for r in noted]
        formats = [fm.text, fm.text, fm.int, fm.wrap] + ([fm.text] if team else []) + [fm.text, fm.date, fm.stamp, fm.wrap]
        ws.add_table(top + 1, 0, top + 1 + len(data), len(headers) - 1, {
            "data": data, "style": "Table Style Light 1", "autofilter": True,
            "columns": [{"header": h, "header_format": fm.th, "format": f} for h, f in zip(headers, formats)]})
    else:
        ws.write(top + 1, 0, "No notes written yet.", fm.muted)
    ws.set_landscape()
    ws.fit_to_pages(1, 0)

    # -- all tests (the data the Summary formulas read) --------------------------------------------
    ws = wb.add_worksheet(DATA_SHEET)
    ws.set_tab_color(HEAD)
    getters = [lambda r: r.id, lambda r: r.title, lambda r: r.category, lambda r: r.mark, lambda r: r.status,
               lambda r: r.outcome, lambda r: r.owner, lambda r: r.source, lambda r: r.deadline,
               lambda r: r.days_overdue, lambda r: r.created, lambda r: r.updated, lambda r: r.notes]
    formats = [fm.int, fm.wrap, fm.text, fm.text, fm.text, fm.text, fm.text, fm.text, fm.date, fm.int,
               fm.stamp, fm.stamp, fm.wrap]
    widths = [7, 38, 16, 13, 13, 11, 18, 16, 12, 13, 17, 17, 60]
    _table(ws, 0, 0, list(zip(DATA_HEADERS, widths, formats, getters)), rows, fm)
    ws.freeze_panes(1, 0)
    ws.set_landscape()
    ws.fit_to_pages(1, 0)

    wb.close()
    return out.getvalue()


def _csv_safe(value: str) -> str:
    """Stop spreadsheet apps from running a cell that starts like a formula."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def build_csv(rows: list[Row]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(DATA_HEADERS)
    for r in rows:
        writer.writerow([
            r.id, _csv_safe(r.title), _csv_safe(r.category), r.mark, r.status, r.outcome, _csv_safe(r.owner),
            _csv_safe(r.source), r.deadline.isoformat() if r.deadline else "", r.days_overdue or "",
            f"{r.created:%Y-%m-%d %H:%M}" if r.created else "", f"{r.updated:%Y-%m-%d %H:%M}" if r.updated else "",
            _csv_safe(r.notes),
        ])
    return buf.getvalue().encode("utf-8-sig")  # the BOM makes Excel read Hebrew and emoji correctly


def save_report(folder: Path, tasks: list[dict], *, scope_label: str, scope_slug: str, generated_by: str,
                team: bool, now: Optional[datetime] = None) -> Export:
    """Write the .xlsx report and the .csv data next to each other; the folder is created if needed."""
    now = now or datetime.now()
    rows = to_rows(tasks, now.date())
    folder.mkdir(parents=True, exist_ok=True)
    base = f"Gate Tasks report - {scope_slug} - {now:%Y-%m-%d %H-%M-%S}"
    stem, n = base, 2
    while (folder / f"{stem}.xlsx").exists() or (folder / f"{stem}.csv").exists():
        stem, n = f"{base} ({n})", n + 1
    data = build_workbook(rows, scope_label=scope_label, generated_by=generated_by, now=now, team=team)
    xlsx, csv_path = folder / f"{stem}.xlsx", folder / f"{stem}.csv"
    xlsx.write_bytes(data)
    csv_path.write_bytes(build_csv(rows))
    return Export(folder=folder, xlsx=xlsx, csv=csv_path, data=data)
