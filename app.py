from flask import Flask, request, redirect, Response
import csv
import io
import sqlite3
import logging
from markupsafe import escape
logging.basicConfig(level=logging.ERROR)

app = Flask(__name__)

DATABASE = "helpdesk.db"
VALID_PRIORITIES = ("Low", "Medium", "High")
VALID_STATUSES = ("Open", "In Progress", "Resolved")


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_database():
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            priority TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Open'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ticket_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (ticket_id) REFERENCES tickets(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ticket_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_id INTEGER NOT NULL,
            comment TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (ticket_id) REFERENCES tickets(id)
        )
    """)
    conn.commit()
    conn.close()


@app.route("/", methods=["GET", "POST"])
def home():
    if request.method == "POST":
        employee = request.form.get("employee", "").strip()
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        priority = request.form.get("priority", "Medium").strip()

        if not employee or not title or not description:
            return "Please fill in all required fields.", 400
        if len(employee) > 100 or len(title) > 200 or len(description) > 5000:
            return "One or more fields exceed the allowed length.", 400
        if priority not in VALID_PRIORITIES:
            return "Invalid priority.", 400

        conn = get_db_connection()
        cursor = conn.execute(
            "INSERT INTO tickets (employee, title, description, priority) VALUES (?, ?, ?, ?)",
            (employee, title, description, priority),
        )
        ticket_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO ticket_activity (ticket_id, action, details) VALUES (?, ?, ?)",
            (ticket_id, "Created", f"Ticket created by {employee}"),
        )
        conn.commit()
        conn.close()
        return redirect("/")

    conn = get_db_connection()
    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "")
    priority_filter = request.args.get("priority", "")
    where = []
    params = []

    if search:
        where.append("(employee LIKE ? OR title LIKE ? OR description LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
    if status_filter in VALID_STATUSES:
        where.append("status = ?")
        params.append(status_filter)
    if priority_filter in VALID_PRIORITIES:
        where.append("priority = ?")
        params.append(priority_filter)

    sql = "SELECT * FROM tickets"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC"
    tickets = conn.execute(sql, params).fetchall()
    counts = {
        status: conn.execute(
            "SELECT COUNT(*) FROM tickets WHERE status = ?", (status,)
        ).fetchone()[0]
        for status in VALID_STATUSES
    }
    priority_counts = {
        priority: conn.execute(
            "SELECT COUNT(*) FROM tickets WHERE priority = ?", (priority,)
        ).fetchone()[0]
        for priority in VALID_PRIORITIES
    }
    total = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    conn.close()

    # Dashboard charts use all tickets, independent of the current search filters.
    status_chart = "".join(
        f"<div class='chart-row'><div class='chart-label'><span>{escape(status)}</span><strong>{counts[status]}</strong></div>"
        f"<div class='bar-track'><div class='bar status-bar-{status.lower().replace(' ', '-')}' style='width:{(counts[status] / total * 100) if total else 0:.1f}%'></div></div></div>"
        for status in VALID_STATUSES
    )
    priority_chart = "".join(
        f"<div class='chart-row'><div class='chart-label'><span>{escape(priority)}</span><strong>{priority_counts[priority]}</strong></div>"
        f"<div class='bar-track'><div class='bar priority-bar-{priority.lower()}' style='width:{(priority_counts[priority] / total * 100) if total else 0:.1f}%'></div></div></div>"
        for priority in VALID_PRIORITIES
    )
    resolved_percent = round(counts["Resolved"] / total * 100) if total else 0

    rows = ""
    for ticket in tickets:
        status = ticket["status"]
        priority = ticket["priority"]
        options = "".join(
            f'<option value="{s}" {"selected" if s == status else ""}>{s}</option>'
            for s in VALID_STATUSES
        )
        rows += f"""
            <tr>
                <td><a href="/ticket/{ticket['id']}">#{ticket['id']}</a></td>
                <td><strong><a href="/ticket/{ticket['id']}" class="issue-link">{escape(ticket['title'])}</a></strong>
                    <div class="muted">{escape(ticket['description'])}</div></td>
                <td>{escape(ticket['employee'])}</td>
                <td><span class="priority {priority.lower()}">{escape(priority)}</span></td>
                <td><span class="status">{escape(status)}</span></td>
                <td><form method="POST" action="/ticket/{ticket['id']}/status" class="update-form">
                    <select name="status" aria-label="Ticket status">{options}</select>
                    <button class="small-btn" type="submit">Update</button>
                </form></td>
            </tr>
        """
    if not rows:
        rows = '<tr><td colspan="6" class="empty">No tickets match. Create your first ticket!</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Smart IT Helpdesk</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;font-family:Arial,sans-serif;background:#f4f6fb;color:#202b40}}
header{{background:#172554;color:white;padding:22px 5%}} header h1{{margin:0 0 6px;font-size:25px}} header p{{margin:0;color:#c7d2fe}}
main{{max-width:1250px;margin:30px auto;padding:0 20px}} .cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:25px}}
.card,.panel{{background:white;padding:22px;border-radius:12px;box-shadow:0 3px 14px #1725540d}} .card-link{{display:block;color:inherit;text-decoration:none;border-radius:12px}} .card-link .card{{height:100%;transition:transform .15s,box-shadow .15s}} .card-link:hover .card{{transform:translateY(-2px);box-shadow:0 6px 18px #1725541a}} .card-link:focus-visible{{outline:3px solid #2563eb;outline-offset:3px}} .card p{{margin:0 0 12px;color:#64748b}} .number{{font-size:30px;font-weight:bold}}
.layout{{display:grid;grid-template-columns:320px minmax(0,1fr);gap:22px;align-items:start}} h2{{font-size:19px;margin-top:0}}
label{{display:block;font-size:14px;font-weight:bold;margin:14px 0 7px}} input,textarea,select{{width:100%;padding:10px;border:1px solid #d7deea;border-radius:7px;font:inherit;background:white}} textarea{{resize:vertical;min-height:100px}}
button{{background:#2563eb;color:white;border:0;padding:11px 15px;border-radius:7px;cursor:pointer;font-weight:bold}} button:hover{{background:#1d4ed8}} .create-btn{{width:100%;margin-top:18px}} .small-btn{{padding:8px;margin-top:7px}}
.table-wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:13px}} th,td{{padding:13px 10px;text-align:left;border-bottom:1px solid #e8edf5;vertical-align:top}} th{{background:#f8fafc;color:#64748b}}
.muted{{color:#64748b;margin-top:6px;overflow-wrap:anywhere}} .priority,.status{{display:inline-block;padding:5px 8px;border-radius:20px;font-size:12px;background:#eef2ff}} .high{{background:#fee2e2;color:#991b1b}} .medium{{background:#fef3c7;color:#92400e}} .low{{background:#dcfce7;color:#166534}} .empty{{text-align:center;padding:30px}} .update-form{{min-width:115px}}
.export-btn{{display:inline-block;background:#0f766e;color:white;padding:10px 14px;border-radius:7px;text-decoration:none;font-weight:bold;margin:0 0 12px}}.export-btn:hover{{background:#115e59}} .filters{{display:grid;grid-template-columns:repeat(2,minmax(140px,1fr));gap:12px;align-items:end;margin-bottom:20px;padding:16px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px}} .filters label{{margin-top:0}} .filters button{{width:100%}} .filters a{{color:#2563eb;text-decoration:none;font-size:14px;padding:10px 0}} .issue-link{{color:#2563eb;text-decoration:none}} footer{{text-align:center;padding:25px;color:#64748b}}
.dashboard-charts{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px;margin:0 0 25px}}.chart-panel{{background:#fff;padding:22px;border-radius:12px;box-shadow:0 3px 14px #1725540d;min-width:0}}.chart-panel h3{{margin:0 0 6px;font-size:17px}}.chart-note{{margin:0 0 18px;color:#64748b;font-size:13px}}.chart-row{{margin:16px 0}}.chart-label{{display:flex;justify-content:space-between;gap:12px;margin-bottom:7px;font-size:14px}}.chart-label strong{{font-variant-numeric:tabular-nums}}.bar-track{{height:12px;background:#edf2f7;border-radius:999px;overflow:hidden}}.bar{{height:100%;border-radius:999px}}.status-bar-open{{background:#3b82f6}}.status-bar-in-progress{{background:#f59e0b}}.status-bar-resolved{{background:#22c55e}}.priority-bar-high{{background:#ef4444}}.priority-bar-medium{{background:#f59e0b}}.priority-bar-low{{background:#22c55e}}.resolution-summary{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:18px;padding-top:15px;border-top:1px solid #e8edf5;color:#64748b;font-size:14px}}.resolution-summary strong{{font-size:20px;color:#202b40}}
@media(max-width:850px){{.layout{{grid-template-columns:1fr}}.cards{{grid-template-columns:repeat(2,1fr)}}.dashboard-charts{{grid-template-columns:1fr}}}} @media(max-width:550px){{.filters{{grid-template-columns:1fr}}main{{padding:0 10px}}.cards{{gap:10px}}.card,.panel,.chart-panel{{padding:16px}}}}
</style></head><body>
<header><h1>Smart IT Helpdesk</h1><p>IT Support &amp; Ticket Management Dashboard</p></header>
<main><h2>Dashboard Overview</h2>
<section class="cards" aria-label="Ticket summary cards">
<a class="card-link" href="/" aria-label="View all tickets"><div class="card"><p>Total Tickets · View all</p><div class="number">{total}</div></div></a>
<a class="card-link" href="/?status=Open" aria-label="View open tickets"><div class="card"><p>Open · View tickets</p><div class="number">{counts['Open']}</div></div></a>
<a class="card-link" href="/?status=In%20Progress" aria-label="View tickets in progress"><div class="card"><p>In Progress · View tickets</p><div class="number">{counts['In Progress']}</div></div></a>
<a class="card-link" href="/?status=Resolved" aria-label="View resolved tickets"><div class="card"><p>Resolved · View tickets</p><div class="number">{counts['Resolved']}</div></div></a>
</section>
<section class="dashboard-charts" aria-label="Ticket charts">
<div class="chart-panel"><h3>Tickets by Status</h3><p class="chart-note">Distribution across all tickets</p>{status_chart}</div>
<div class="chart-panel"><h3>Tickets by Priority</h3><p class="chart-note">Compare high, medium and low priority</p>{priority_chart}<div class="resolution-summary"><span>Resolution rate</span><strong>{resolved_percent}%</strong></div></div>
</section>
<section class="layout">
<div class="panel"><h2>Create Ticket</h2><form method="POST">
<label for="employee">Employee Name</label><input id="employee" name="employee" maxlength="100" required>
<label for="title">Issue Title</label><input id="title" name="title" maxlength="200" required>
<label for="description">Description</label><textarea id="description" name="description" maxlength="5000" required></textarea>
<label for="priority">Priority</label><select id="priority" name="priority"><option>Low</option><option selected>Medium</option><option>High</option></select>
<button class="create-btn" type="submit">+ Create Ticket</button></form></div>
<div class="panel"><h2>Support Tickets</h2><p><a class="export-btn" href="/export/tickets.csv">&#8595; Export Tickets to CSV</a></p><form method="GET" class="filters">
<div><label for="search">Search employee or issue</label><input id="search" type="text" name="search" placeholder="e.g. Wi-Fi or Ravi" value="{escape(search)}"></div>
<div><label for="status-filter">Filter by status</label><select id="status-filter" name="status"><option value="">All statuses</option>{''.join(f'<option value="{s}" {"selected" if status_filter == s else ""}>{s}</option>' for s in VALID_STATUSES)}</select></div>
<div><label for="priority-filter">Filter by priority</label><select id="priority-filter" name="priority"><option value="">All priorities</option>{''.join(f'<option value="{p}" {"selected" if priority_filter == p else ""}>{p}</option>' for p in VALID_PRIORITIES)}</select></div>
<div><button type="submit">Search / Filter</button><p><a href="/">Clear filters</a></p></div></form>
<div class="table-wrap"><table><thead><tr><th>ID</th><th>Issue</th><th>Employee</th><th>Priority</th><th>Status</th><th>Manage</th></tr></thead><tbody>{rows}</tbody></table></div>
</div></section></main><footer>Smart IT Helpdesk · Learning Project</footer></body></html>"""


@app.route("/ticket/<int:ticket_id>")
def ticket_details(ticket_id):
    conn = get_db_connection()
    try:
        ticket = conn.execute(
            "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
        ).fetchone()

        if ticket is None:
            return "Ticket not found.", 404

        comments = conn.execute(
            "SELECT * FROM ticket_comments WHERE ticket_id = ? ORDER BY created_at DESC, id DESC",
            (ticket_id,),
        ).fetchall()

        activity = conn.execute(
            "SELECT * FROM ticket_activity WHERE ticket_id = ? ORDER BY created_at DESC, id DESC",
            (ticket_id,),
        ).fetchall()
    finally:
        conn.close()
        return "Ticket not found.", 404

    comment_html = "".join(
        f"<div class='entry'><p>{escape(comment['comment'])}</p><small>{escape(str(comment['created_at']))}</small></div>"
        for comment in comments
    ) or "<p>No comments yet.</p>"
    activity_html = "".join(
        f"<div class='entry'><strong>{escape(item['action'])}</strong><p>{escape(item['details'])}</p><small>{escape(str(item['created_at']))}</small></div>"
        for item in activity
    ) or "<p>No activity recorded yet.</p>"

    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Ticket #{ticket['id']} | IT Helpdesk</title>
<style>
*{{box-sizing:border-box}}body{{font-family:Arial,sans-serif;background:#f4f6fb;color:#202b40;margin:0;padding:35px 16px}}
.ticket{{max-width:760px;margin:0 auto;background:white;border-radius:14px;box-shadow:0 5px 24px #0f172a14;overflow:hidden}}
.header{{background:#1e293b;color:white;padding:25px 30px}}.header h1{{margin:0 0 8px;font-size:25px}}.header p{{margin:0;color:#cbd5e1;font-size:14px}}
.content,.section{{padding:25px 30px}}.field{{margin-bottom:24px}}.label{{color:#64748b;font-size:12px;font-weight:bold;text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px}}
.value{{font-size:16px;line-height:1.7;overflow-wrap:anywhere;white-space:pre-wrap}}.badge{{display:inline-block;background:#e2e8f0;color:#334155;padding:6px 12px;border-radius:20px;font-size:13px;font-weight:bold}}
.section{{border-top:1px solid #e2e8f0}}.section h2{{margin-top:0;font-size:20px}}textarea,input,select{{width:100%;padding:11px;border:1px solid #cbd5e1;border-radius:8px;font:inherit;margin:6px 0 12px}}textarea{{min-height:100px;resize:vertical}}
button,.link{{display:inline-block;background:#2563eb;color:white;padding:11px 16px;border:0;border-radius:8px;text-decoration:none;font-weight:bold;cursor:pointer}}.secondary{{background:#475569}}.entry{{padding:12px;margin-bottom:10px;background:#f8fafc;border-radius:8px;overflow-wrap:anywhere}}.entry p{{white-space:pre-wrap}}small{{color:#64748b}}.footer{{border-top:1px solid #e2e8f0;padding:20px 30px;display:flex;gap:10px;flex-wrap:wrap}}
@media(max-width:500px){{body{{padding:18px 10px}}.header,.content,.section,.footer{{padding:20px}}}}



.card-link {{
    display: block;
    text-decoration: none;
    color: inherit;
    cursor: pointer;
}}

.card-link .card {{
    height: 100%;
    transition: transform 0.2s, box-shadow 0.2s;
}}

.card-link:hover .card {{
    transform: translateY(-3px);
    box-shadow: 0 6px 18px #17255420;
}}

</style></head><body><div class="ticket">
<div class="header"><h1>Ticket #{ticket['id']}</h1><p>IT Helpdesk / Ticket Details</p></div>
<div class="content">
<div class="field"><div class="label">Issue Title</div><div class="value">{escape(ticket['title'])}</div></div>
<div class="field"><div class="label">Description</div><div class="value">{escape(ticket['description'])}</div></div>
<div class="field"><div class="label">Employee</div><div class="value">{escape(ticket['employee'])}</div></div>
<div class="field"><div class="label">Priority</div><span class="badge">{escape(ticket['priority'])}</span></div>
<div class="field"><div class="label">Current Status</div><span class="badge">{escape(ticket['status'])}</span></div>
<a class="link" href="/ticket/{ticket['id']}/edit">Edit Ticket Details</a>
</div>
<div class="section"><h2>Ticket Comments</h2><form action="/ticket/{ticket['id']}/comments" method="POST">
<label for="comment">Add a comment</label><textarea id="comment" name="comment" maxlength="5000" placeholder="Write a comment..." required></textarea><button type="submit">Add Comment</button></form>
<h3>Previous Comments</h3>{comment_html}</div>
<div class="section"><h2>Activity History</h2>{activity_html}</div>
<div class="footer"><a class="link" href="/">← Back to Dashboard</a></div></div></body></html>"""


@app.route("/ticket/<int:ticket_id>/edit", methods=["GET", "POST"])
def edit_ticket(ticket_id):
    conn = get_db_connection()
    ticket = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if ticket is None:
        conn.close()
        return "Ticket not found.", 404

    if request.method == "POST":
        employee = request.form.get("employee", "").strip()
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        priority = request.form.get("priority", "").strip()
        if not employee or not title or not description:
            conn.close()
            return "Please fill in all required fields.", 400
        if len(employee) > 100 or len(title) > 200 or len(description) > 5000:
            conn.close()
            return "One or more fields exceed the allowed length.", 400
        if priority not in VALID_PRIORITIES:
            conn.close()
            return "Invalid priority.", 400

        changes = []
        for field, label, new_value in (
            ("employee", "Employee", employee),
            ("title", "Title", title),
            ("description", "Description", description),
            ("priority", "Priority", priority),
        ):
            old_value = ticket[field]
            if old_value != new_value:
                changes.append(f"{label} changed from '{old_value}' to '{new_value}'")

        if changes:
            conn.execute(
                "UPDATE tickets SET employee = ?, title = ?, description = ?, priority = ? WHERE id = ?",
                (employee, title, description, priority, ticket_id),
            )
            conn.execute(
                "INSERT INTO ticket_activity (ticket_id, action, details) VALUES (?, ?, ?)",
                (ticket_id, "Ticket Edited", "; ".join(changes)),
            )
            conn.commit()
        conn.close()
        return redirect(f"/ticket/{ticket_id}")

    conn.close()
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Edit Ticket #{ticket['id']} | IT Helpdesk</title><style>
*{{box-sizing:border-box}}body{{font-family:Arial,sans-serif;background:#f4f6fb;color:#202b40;margin:0;padding:30px 15px}}.panel{{max-width:700px;margin:auto;background:white;padding:28px;border-radius:14px;box-shadow:0 5px 24px #0f172a14}}h1{{margin-top:0}}label{{display:block;font-weight:bold;margin:16px 0 7px}}input,textarea,select{{width:100%;padding:11px;border:1px solid #cbd5e1;border-radius:8px;font:inherit}}textarea{{min-height:130px;resize:vertical}}button,.link{{display:inline-block;margin-top:18px;background:#2563eb;color:white;padding:11px 16px;border:0;border-radius:8px;text-decoration:none;font-weight:bold;cursor:pointer}}.link{{background:#475569;margin-left:8px}}small{{color:#64748b}}
</style></head><body><main class="panel"><h1>Edit Ticket #{ticket['id']}</h1><p>Update the ticket information below.</p>
<form method="POST" action="/ticket/{ticket_id}/edit">
<label for="employee">Employee Name</label><input id="employee" name="employee" maxlength="100" value="{escape(ticket['employee'])}" required>
<label for="title">Issue Title</label><input id="title" name="title" maxlength="200" value="{escape(ticket['title'])}" required>
<label for="description">Description</label><textarea id="description" name="description" maxlength="5000" required>{escape(ticket['description'])}</textarea>
<label for="priority">Priority</label><select id="priority" name="priority">{''.join(f'<option value="{p}" {"selected" if p == ticket["priority"] else ""}>{p}</option>' for p in VALID_PRIORITIES)}</select>
<button type="submit">Save Changes</button><a class="link" href="/ticket/{ticket_id}">Cancel</a></form></main></body></html>"""


@app.route("/ticket/<int:ticket_id>/comments", methods=["POST"])
def add_ticket_comment(ticket_id):
    comment = request.form.get("comment", "").strip()
    if not comment:
        return redirect(f"/ticket/{ticket_id}")
    if len(comment) > 5000:
        return "Comment is too long.", 400

    conn = get_db_connection()
    ticket = conn.execute("SELECT id FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if ticket is None:
        conn.close()
        return "Ticket not found.", 404
    conn.execute(
        "INSERT INTO ticket_comments (ticket_id, comment) VALUES (?, ?)",
        (ticket_id, comment),
    )
    conn.execute(
        "INSERT INTO ticket_activity (ticket_id, action, details) VALUES (?, ?, ?)",
        (ticket_id, "Comment Added", "A comment was added to this ticket."),
    )
    conn.commit()
    conn.close()
    return redirect(f"/ticket/{ticket_id}")


@app.route("/ticket/<int:ticket_id>/status", methods=["POST"])
def update_ticket_status(ticket_id):
    new_status = request.form.get("status", "").strip()
    if new_status not in VALID_STATUSES:
        return "Invalid status.", 400

    conn = get_db_connection()
    ticket = conn.execute("SELECT status FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if ticket is None:
        conn.close()
        return "Ticket not found.", 404
    old_status = ticket["status"]
    if old_status != new_status:
        conn.execute("UPDATE tickets SET status = ? WHERE id = ?", (new_status, ticket_id))
        conn.execute(
            "INSERT INTO ticket_activity (ticket_id, action, details) VALUES (?, ?, ?)",
            (ticket_id, "Status Changed", f"Status changed from {old_status} to {new_status}"),
        )
    conn.commit()
    conn.close()
    return redirect("/")


@app.route("/export/tickets.csv")
def export_tickets_csv():
    """Download all helpdesk tickets as a CSV spreadsheet."""
    conn = get_db_connection()
    tickets = conn.execute(
        "SELECT id, employee, title, description, priority, status FROM tickets ORDER BY id DESC"
    ).fetchall()
    conn.close()

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Ticket ID", "Employee Name", "Issue Title", "Description", "Priority", "Status"])
    for ticket in tickets:
        writer.writerow([
            ticket["id"], ticket["employee"], ticket["title"],
            ticket["description"], ticket["priority"], ticket["status"],
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=smart_it_helpdesk_tickets.csv"},
    )


initialize_database()
@app.errorhandler(404)
def page_not_found(error):
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Page Not Found | IT Helpdesk</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: #f4f6fb;
                color: #202b40;
                text-align: center;
                padding: 80px 20px;
            }
            a {
                color: #2563eb;
            }
        </style>
    </head>
    <body>
        <h1>404 - Page Not Found</h1>
        <p>The page you are looking for does not exist.</p>
        <a href="/">Return to Dashboard</a>
    </body>
    </html>
    """, 404


@app.errorhandler(500)
def internal_server_error(error):
    app.logger.error("Internal server error: %s", error)
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Server Error | IT Helpdesk</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: #f4f6fb;
                color: #202b40;
                text-align: center;
                padding: 80px 20px;
            }
            a {
                color: #2563eb;
            }
        </style>
    </head>
    <body>
        <h1>500 - Something Went Wrong</h1>
        <p>An unexpected server error occurred. Please try again later.</p>
        <a href="/">Return to Dashboard</a>
    </body>
    </html>
    """, 500

if __name__ == "__main__":
    app.run(debug=True)
