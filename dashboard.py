"""Emails an end-of-day dashboard from the applications table.

Runs in GitHub Actions at 11pm Toronto time (.github/workflows/dashboard.yml).
GitHub Actions cron is UTC-only, so the workflow fires at both possible UTC
times for 11pm Toronto (EDT and EST) and this script only actually sends once
the local time really is 11pm - the other trigger exits immediately.

  python dashboard.py            only sends if it's 11pm in Toronto right now
  python dashboard.py --force    sends regardless of the time (for testing)
"""
import argparse
import html
import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")  # no display in CI or when testing from a terminal
import matplotlib.pyplot as plt

import db
import excel_export
from emailer import EMAIL_ADDRESS, send_html_email_with_image

RECIPIENT = "anshvaishnav@gmail.com"

# Single-series categorical slot 1 from the dataviz skill's validated palette.
BAR_COLOR = "#2a78d6"
SURFACE_COLOR = "#fcfcfb"
TEXT_PRIMARY = "#0b0b0b"
TEXT_SECONDARY = "#52514e"
GRID_COLOR = "#e5e3dc"


def toronto_now():
    return datetime.now(ZoneInfo("America/Toronto"))


def fetch_counts(conn):
    today = toronto_now().date()
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM applications WHERE status='submitted' AND applied_at::date = %s", (today,))
        today_count = cur.fetchone()[0]
        cur.execute("""SELECT count(*) FROM applications WHERE status='submitted'
                       AND applied_at >= date_trunc('week', now() AT TIME ZONE 'America/Toronto')
                                        AT TIME ZONE 'America/Toronto'""")
        week_count = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM applications WHERE status='submitted'")
        all_time_count = cur.fetchone()[0]
    return today_count, week_count, all_time_count


def fetch_ats_breakdown(conn):
    with conn.cursor() as cur:
        cur.execute("""SELECT ats, count(*) FROM applications WHERE status='submitted'
                       GROUP BY ats ORDER BY count(*) DESC""")
        return cur.fetchall()


def fetch_rows(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetch_today_submitted(conn):
    today = toronto_now().date()
    return fetch_rows(conn, """SELECT company, title, url, ats, location, applied_at FROM applications
                                WHERE status='submitted' AND applied_at::date = %s ORDER BY applied_at""", (today,))


def fetch_needs_review(conn, limit=25):
    return fetch_rows(conn, """SELECT company, title, url, status_reason, draft_answer FROM applications
                                WHERE status='needs_review' ORDER BY found_at DESC LIMIT %s""", (limit,))


def fetch_today_failed(conn):
    today = toronto_now().date()
    return fetch_rows(conn, """SELECT company, title, url, status_reason FROM applications
                                WHERE status='failed' AND applied_at::date = %s ORDER BY applied_at""", (today,))


def fetch_daily_counts(conn, days=14):
    with conn.cursor() as cur:
        cur.execute(f"""SELECT applied_at::date AS d, count(*) FROM applications
                       WHERE status='submitted' AND applied_at >= now() - interval '{int(days)} days'
                       GROUP BY 1""")
        by_day = {row[0]: row[1] for row in cur.fetchall()}
    today = toronto_now().date()
    return [(today - timedelta(days=offset), by_day.get(today - timedelta(days=offset), 0))
            for offset in range(days - 1, -1, -1)]


def build_chart(daily_counts):
    dates = [d for d, _ in daily_counts]
    counts = [c for _, c in daily_counts]
    today_idx = len(dates) - 1
    peak_idx = max(range(len(counts)), key=lambda i: counts[i]) if any(counts) else None

    fig, ax = plt.subplots(figsize=(6.4, 2.8), dpi=150)
    fig.patch.set_facecolor(SURFACE_COLOR)
    ax.set_facecolor(SURFACE_COLOR)

    bars = ax.bar(range(len(dates)), counts, width=0.55, color=BAR_COLOR, zorder=3)
    for bar in bars:
        bar.set_clip_on(False)

    ax.set_ylim(bottom=0)
    max_count = max(counts) if counts else 0
    ax.set_yticks(range(0, max_count + 2, max(1, (max_count + 2) // 4)))
    ax.set_xticks(range(len(dates)))
    ax.set_xticklabels([d.strftime("%-m/%-d") for d in dates], fontsize=8, color=TEXT_SECONDARY)
    ax.tick_params(axis="y", labelsize=8, colors=TEXT_SECONDARY, length=0)
    ax.tick_params(axis="x", length=0)

    ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.8, zorder=0)
    ax.xaxis.grid(False)
    for spine in ax.spines.values():
        spine.set_visible(False)

    # Direct labels only on the two bars worth calling out, per the skill's
    # "selective direct labels" rule - not a number crowding every bar.
    if peak_idx is not None and counts[peak_idx] > 0:
        ax.text(peak_idx, counts[peak_idx] + 0.15, str(counts[peak_idx]), ha="center",
                fontsize=8, color=TEXT_PRIMARY, fontweight="bold")
    if today_idx != peak_idx:
        ax.text(today_idx, counts[today_idx] + 0.15, str(counts[today_idx]), ha="center",
                fontsize=8, color=TEXT_PRIMARY)

    ax.set_title("Applications submitted, last 14 days", fontsize=10, color=TEXT_PRIMARY, loc="left", pad=10)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=SURFACE_COLOR)
    plt.close(fig)
    return buf.getvalue()


def esc(text):
    return html.escape(str(text or ""))


def row_link(url, label):
    return f'<a href="{esc(url)}" style="color:#1a73e8; text-decoration:none;">{esc(label)}</a>'


def build_html(stats, ats_breakdown, today_submitted, needs_review, today_failed):
    today_count, week_count, all_time_count = stats

    stat_row = f"""
    <table style="width:100%; border-collapse:collapse; margin-bottom:20px;">
      <tr>
        <td style="padding:12px; text-align:center; background:#f5f5f5; border-radius:8px 0 0 8px;">
          <div style="font-size:24px; font-weight:700;">{today_count}</div>
          <div style="font-size:12px; color:#666;">Today</div>
        </td>
        <td style="padding:12px; text-align:center; background:#f5f5f5;">
          <div style="font-size:24px; font-weight:700;">{week_count}</div>
          <div style="font-size:12px; color:#666;">This week</div>
        </td>
        <td style="padding:12px; text-align:center; background:#f5f5f5; border-radius:0 8px 8px 0;">
          <div style="font-size:24px; font-weight:700;">{all_time_count}</div>
          <div style="font-size:12px; color:#666;">All time</div>
        </td>
      </tr>
    </table>"""

    ats_rows = "".join(f"<tr><td style='padding:6px 12px;'>{esc(ats)}</td>"
                       f"<td style='padding:6px 12px;'>{count}</td></tr>" for ats, count in ats_breakdown)
    ats_section = (f"<h3>Breakdown by ATS</h3><table style='border-collapse:collapse; font-size:14px;'>{ats_rows}</table>"
                  if ats_breakdown else "<h3>Breakdown by ATS</h3><p style='color:#666;'>No submissions yet.</p>")

    def company_title(r):
        return f"{r['company']} - {r['title']}"

    if today_submitted:
        rows = "".join(f"<li>{row_link(r['url'], company_title(r))} ({esc(r['ats'])})</li>"
                       for r in today_submitted)
        today_section = f"<h3>Applied today ({len(today_submitted)})</h3><ul style='font-size:14px;'>{rows}</ul>"
    else:
        today_section = "<h3>Applied today</h3><p style='color:#666;'>None today.</p>"

    if needs_review:
        items = []
        for r in needs_review:
            draft = (f"<div style='margin-top:4px; padding:8px; background:#fffbea; border-radius:4px; "
                    f"font-size:13px; white-space:pre-wrap;'>{esc(r['draft_answer'])}</div>"
                    if r.get("draft_answer") else "")
            items.append(f"<li>{row_link(r['url'], company_title(r))}"
                        f"<div style='font-size:13px; color:#666;'>{esc(r['status_reason'])}</div>{draft}</li>")
        review_section = f"<h3>Needs review ({len(needs_review)})</h3><ul style='font-size:14px;'>{''.join(items)}</ul>"
    else:
        review_section = "<h3>Needs review</h3><p style='color:#666;'>Nothing waiting on you.</p>"

    if today_failed:
        rows = "".join(f"<li>{row_link(r['url'], company_title(r))}"
                       f"<div style='font-size:13px; color:#666;'>{esc(r['status_reason'])}</div></li>"
                       for r in today_failed)
        failed_section = f"<h3>Failures today ({len(today_failed)})</h3><ul style='font-size:14px;'>{rows}</ul>"
    else:
        failed_section = "<h3>Failures today</h3><p style='color:#666;'>None today.</p>"

    return f"""
    <html>
    <body style="font-family:Arial, sans-serif; max-width:700px; margin:0 auto; color:#222;">
        <h2>Auto-apply dashboard - {toronto_now().strftime('%A, %B %-d')}</h2>
        {stat_row}
        <img src="cid:dailychart" style="width:100%; max-width:640px; display:block; margin-bottom:20px;">
        {ats_section}
        {today_section}
        {review_section}
        {failed_section}
    </body>
    </html>
    """


def main(force=False):
    now = toronto_now()
    if not force and now.hour != 23:
        print(f"Not 11pm Toronto time yet ({now}), skipping this trigger.")
        return

    conn = db.get_connection()
    if conn is None:
        print("Warning: could not connect to the database, skipping the dashboard email.")
        return

    stats = fetch_counts(conn)
    ats_breakdown = fetch_ats_breakdown(conn)
    today_submitted = fetch_today_submitted(conn)
    needs_review = fetch_needs_review(conn)
    today_failed = fetch_today_failed(conn)
    daily_counts = fetch_daily_counts(conn)

    chart_bytes = build_chart(daily_counts)
    html_body = build_html(stats, ats_breakdown, today_submitted, needs_review, today_failed)

    send_html_email_with_image(
        to_address=RECIPIENT,
        subject=f"Auto-apply dashboard - {stats[0]} applied today",
        html_body=html_body,
        image_bytes=chart_bytes,
        image_cid="dailychart",
    )
    print(f"Sent dashboard email to {RECIPIENT}")

    excel_export.append_submitted_jobs(today_submitted)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="send now regardless of the time")
    args = parser.parse_args()
    main(force=args.force)
