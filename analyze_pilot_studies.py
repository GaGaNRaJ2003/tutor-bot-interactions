from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import xlsxwriter


ROOT = Path(__file__).resolve().parent


@dataclass
class MessageFileStats:
    user_id: str
    session_id: str
    message_count: int
    observed_seconds: float


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def iter_message_file_stats(messages_root: Path) -> list[MessageFileStats]:
    stats: list[MessageFileStats] = []
    if not messages_root.exists():
        return stats

    for user_dir in sorted(p for p in messages_root.iterdir() if p.is_dir()):
        for message_file in sorted(user_dir.glob("*.json")):
            payload = load_json(message_file)
            if isinstance(payload, list):
                messages = payload
            elif payload is None:
                messages = []
            else:
                messages = [payload]

            timestamps = sorted(
                dt
                for dt in (parse_dt(item.get("created_at")) for item in messages if isinstance(item, dict))
                if dt is not None
            )
            observed_seconds = 0.0
            if len(timestamps) >= 2:
                observed_seconds = (timestamps[-1] - timestamps[0]).total_seconds()

            stats.append(
                MessageFileStats(
                    user_id=user_dir.name,
                    session_id=message_file.stem,
                    message_count=len(messages),
                    observed_seconds=observed_seconds,
                )
            )
    return stats


def build_global_user_lookup(pilot_dirs: list[Path]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for pilot_dir in pilot_dirs:
        users = load_json(pilot_dir / "users.json")
        for user in users:
            user_id = user.get("id")
            if isinstance(user_id, str) and user_id not in lookup:
                lookup[user_id] = user
    return lookup


def best_label_for_user(user_id: str, pilot_user: dict[str, Any] | None, global_user_lookup: dict[str, dict[str, Any]]) -> str:
    if pilot_user and pilot_user.get("display_name"):
        return str(pilot_user["display_name"]).strip()
    global_user = global_user_lookup.get(user_id)
    if global_user and global_user.get("display_name"):
        return str(global_user["display_name"]).strip()
    return user_id


def analyze_pilot(pilot_dir: Path, global_user_lookup: dict[str, dict[str, Any]]) -> dict[str, Any]:
    users = load_json(pilot_dir / "users.json")
    sessions = load_json(pilot_dir / "sessions.json")
    prompt_versions = load_json(pilot_dir / "prompt_versions.json")
    message_file_stats = iter_message_file_stats(pilot_dir / "messages")

    users_by_id = {user["id"]: user for user in users}

    per_user_messages: dict[str, int] = {}
    per_user_seconds: dict[str, float] = {}
    orphaned_message_users: dict[str, int] = {}
    for item in message_file_stats:
        per_user_messages[item.user_id] = per_user_messages.get(item.user_id, 0) + item.message_count
        per_user_seconds[item.user_id] = per_user_seconds.get(item.user_id, 0.0) + item.observed_seconds
        if item.user_id not in users_by_id:
            orphaned_message_users[item.user_id] = orphaned_message_users.get(item.user_id, 0) + item.message_count

    per_user_sessions: dict[str, int] = {}
    orphaned_session_users: dict[str, int] = {}
    for session in sessions:
        user_id = session.get("user_id")
        if not user_id:
            continue
        per_user_sessions[user_id] = per_user_sessions.get(user_id, 0) + 1
        if user_id not in users_by_id:
            orphaned_session_users[user_id] = orphaned_session_users.get(user_id, 0) + 1

    per_user_new_prompt_versions: dict[str, int] = {}
    orphaned_prompt_users: dict[str, int] = {}
    for version in prompt_versions:
        user_id = version.get("user_id")
        version_number = version.get("version_number")
        if not user_id or not isinstance(version_number, int) or version_number <= 0:
            continue
        per_user_new_prompt_versions[user_id] = per_user_new_prompt_versions.get(user_id, 0) + 1
        if user_id not in users_by_id:
            orphaned_prompt_users[user_id] = orphaned_prompt_users.get(user_id, 0) + 1

    message_file_counts: dict[str, int] = {}
    for item in message_file_stats:
        message_file_counts[item.user_id] = message_file_counts.get(item.user_id, 0) + 1

    user_rows: list[dict[str, Any]] = []
    for user in sorted(users, key=lambda row: (str(row.get("display_name", "")).strip().lower(), row["id"])):
        user_id = user["id"]
        user_rows.append(
            {
                "pilot": pilot_dir.name,
                "user_id": user_id,
                "display_name": user.get("display_name"),
                "email": user.get("email"),
                "is_admin": bool(user.get("is_admin")),
                "registered": True,
                "sessions": per_user_sessions.get(user_id, 0),
                "message_files": message_file_counts.get(user_id, 0),
                "messages": per_user_messages.get(user_id, 0),
                "time_minutes": round(per_user_seconds.get(user_id, 0.0) / 60.0, 2),
                "new_prompt_versions": per_user_new_prompt_versions.get(user_id, 0),
            }
        )

    interaction_user_ids = set(per_user_messages) | set(per_user_sessions) | set(per_user_new_prompt_versions)
    interaction_rows: list[dict[str, Any]] = []
    for user_id in sorted(interaction_user_ids):
        user = users_by_id.get(user_id)
        interaction_rows.append(
            {
                "pilot": pilot_dir.name,
                "user_id": user_id,
                "plot_label": best_label_for_user(user_id, user, global_user_lookup),
                "display_name": user.get("display_name") if user else None,
                "email": user.get("email") if user else None,
                "is_admin": bool(user.get("is_admin")) if user else None,
                "registered_in_pilot": user_id in users_by_id,
                "sessions": per_user_sessions.get(user_id, 0),
                "message_files": message_file_counts.get(user_id, 0),
                "messages": per_user_messages.get(user_id, 0),
                "time_minutes": round(per_user_seconds.get(user_id, 0.0) / 60.0, 2),
                "new_prompt_versions": per_user_new_prompt_versions.get(user_id, 0),
            }
        )

    registered_user_ids = [user["id"] for user in users]
    registered_user_id_set = set(registered_user_ids)

    summary = {
        "pilot": pilot_dir.name,
        "registered_users": len(users),
        "registered_non_admin_users": sum(not bool(user.get("is_admin")) for user in users),
        "active_registered_users_by_messages": sum(row["messages"] > 0 for row in user_rows),
        "registered_user_messages": sum(per_user_messages.get(user_id, 0) for user_id in registered_user_ids),
        "registered_user_time_minutes": round(
            sum(item.observed_seconds for item in message_file_stats if item.user_id in registered_user_id_set) / 60.0, 2
        ),
        "registered_user_new_prompt_versions": sum(
            per_user_new_prompt_versions.get(user_id, 0) for user_id in registered_user_ids
        ),
        "sessions_json_rows": len(sessions),
        "message_files_total_messages_all_users": sum(item.message_count for item in message_file_stats),
        "message_files_total_time_minutes_all_users": round(
            sum(item.observed_seconds for item in message_file_stats) / 60.0, 2
        ),
        "new_prompt_versions_all_users": sum(
            1
            for version in prompt_versions
            if isinstance(version.get("version_number"), int) and version["version_number"] > 0
        ),
        "orphaned_message_users": orphaned_message_users,
        "orphaned_session_users": orphaned_session_users,
        "orphaned_prompt_users": orphaned_prompt_users,
    }

    interaction_summary = {
        "pilot": pilot_dir.name,
        "registered_users": len(users),
        "interaction_user_ids_total": len(interaction_user_ids),
        "interaction_user_ids_registered_in_pilot": sum(row["registered_in_pilot"] for row in interaction_rows),
        "interaction_user_ids_not_registered_in_pilot": sum(not row["registered_in_pilot"] for row in interaction_rows),
        "interaction_sessions": sum(per_user_sessions.get(user_id, 0) for user_id in interaction_user_ids),
        "interaction_messages": sum(per_user_messages.get(user_id, 0) for user_id in interaction_user_ids),
        "interaction_time_minutes": round(
            sum(item.observed_seconds for item in message_file_stats if item.user_id in interaction_user_ids) / 60.0, 2
        ),
        "interaction_new_prompt_versions": sum(
            per_user_new_prompt_versions.get(user_id, 0) for user_id in interaction_user_ids
        ),
    }

    return {
        "summary": summary,
        "users": user_rows,
        "interaction_summary": interaction_summary,
        "interaction_users": interaction_rows,
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_sheet_table(
    workbook: xlsxwriter.Workbook,
    worksheet: xlsxwriter.worksheet.Worksheet,
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    table_name: str,
    start_row: int = 0,
) -> None:
    header_format = workbook.add_format({"bold": True, "bg_color": "#D9EAF7", "border": 1})
    text_format = workbook.add_format({"border": 1})
    int_format = workbook.add_format({"border": 1, "num_format": "0"})
    float_format = workbook.add_format({"border": 1, "num_format": "0.00"})
    bool_format = workbook.add_format({"border": 1})

    for col_idx, (_, header) in enumerate(columns):
        worksheet.write(start_row, col_idx, header, header_format)

    for row_idx, row in enumerate(rows, start=start_row + 1):
        for col_idx, (key, _) in enumerate(columns):
            value = row.get(key)
            if isinstance(value, bool):
                worksheet.write_boolean(row_idx, col_idx, value, bool_format)
            elif isinstance(value, int):
                worksheet.write_number(row_idx, col_idx, value, int_format)
            elif isinstance(value, float):
                worksheet.write_number(row_idx, col_idx, value, float_format)
            elif value is None:
                worksheet.write_blank(row_idx, col_idx, None, text_format)
            else:
                worksheet.write(row_idx, col_idx, str(value), text_format)

    col_settings = [{"header": header} for _, header in columns]
    worksheet.add_table(
        start_row,
        0,
        start_row + max(len(rows), 1),
        len(columns) - 1,
        {"name": table_name, "columns": col_settings},
    )
    worksheet.freeze_panes(start_row + 1, 0)

    for col_idx, (key, header) in enumerate(columns):
        max_len = len(header)
        for row in rows:
            value = row.get(key)
            text = "" if value is None else str(value)
            max_len = max(max_len, len(text))
        worksheet.set_column(col_idx, col_idx, min(max_len + 2, 28))


def add_chart(
    workbook: xlsxwriter.Workbook,
    worksheet: xlsxwriter.worksheet.Worksheet,
    sheet_name: str,
    title: str,
    category_col: int,
    value_col: int,
    row_count: int,
    position: str,
    series_name: str,
    start_row: int = 1,
) -> None:
    if row_count <= 0:
        return
    chart = workbook.add_chart({"type": "column"})
    chart.add_series(
        {
            "name": series_name,
            "categories": [sheet_name, start_row, category_col, start_row + row_count - 1, category_col],
            "values": [sheet_name, start_row, value_col, start_row + row_count - 1, value_col],
            "data_labels": {"value": True},
            "fill": {"color": "#5B8FF9"},
            "border": {"color": "#3B6BD6"},
        }
    )
    chart.set_title({"name": title})
    chart.set_legend({"none": True})
    chart.set_y_axis({"major_gridlines": {"visible": False}})
    chart.set_size({"width": 620, "height": 360})
    worksheet.insert_chart(position, chart)


def create_interaction_workbook(
    path: Path,
    interaction_summary_rows: list[dict[str, Any]],
    interaction_user_rows: list[dict[str, Any]],
) -> None:
    workbook = xlsxwriter.Workbook(path)
    title_format = workbook.add_format({"bold": True, "font_size": 16})
    note_format = workbook.add_format({"italic": True, "font_color": "#666666"})

    summary_sheet = workbook.add_worksheet("Summary")
    summary_sheet.write("A1", "Pilot Interaction View Summary", title_format)
    summary_sheet.write(
        "A2",
        "Counts are grouped by every user_id appearing in interaction data, even if the user_id is not present in users.json.",
        note_format,
    )
    summary_columns = [
        ("pilot", "Pilot"),
        ("registered_users", "Registered Users"),
        ("interaction_user_ids_total", "Interaction User IDs"),
        ("interaction_user_ids_registered_in_pilot", "Registered Interaction IDs"),
        ("interaction_user_ids_not_registered_in_pilot", "Non-Registered Interaction IDs"),
        ("interaction_sessions", "Sessions"),
        ("interaction_messages", "Messages"),
        ("interaction_time_minutes", "Time Minutes"),
        ("interaction_new_prompt_versions", "New Prompt Versions"),
    ]
    write_sheet_table(workbook, summary_sheet, interaction_summary_rows, summary_columns, "InteractionSummary", start_row=3)
    summary_sheet.set_row(0, 24)
    summary_sheet.set_row(1, 36)

    add_chart(workbook, summary_sheet, "Summary", "Messages by Pilot", 0, 6, len(interaction_summary_rows), "K2", "Messages", start_row=4)
    add_chart(
        workbook,
        summary_sheet,
        "Summary",
        "Time Spent by Pilot (Minutes)",
        0,
        7,
        len(interaction_summary_rows),
        "K21",
        "Time Minutes",
        start_row=4,
    )
    add_chart(
        workbook,
        summary_sheet,
        "Summary",
        "New Prompt Versions by Pilot",
        0,
        8,
        len(interaction_summary_rows),
        "K40",
        "New Prompt Versions",
        start_row=4,
    )

    details_sheet = workbook.add_worksheet("Interaction Details")
    details_sheet.write("A1", "Interaction User Details", title_format)
    details_sheet.write(
        "A2",
        "One row per user_id observed in sessions/messages/prompt_versions for each pilot.",
        note_format,
    )
    detail_columns = [
        ("pilot", "Pilot"),
        ("plot_label", "Plot Label"),
        ("user_id", "User ID"),
        ("display_name", "Display Name"),
        ("email", "Email"),
        ("is_admin", "Is Admin"),
        ("registered_in_pilot", "Registered In Pilot"),
        ("sessions", "Sessions"),
        ("message_files", "Message Files"),
        ("messages", "Messages"),
        ("time_minutes", "Time Minutes"),
        ("new_prompt_versions", "New Prompt Versions"),
    ]
    write_sheet_table(workbook, details_sheet, interaction_user_rows, detail_columns, "InteractionDetails", start_row=3)
    details_sheet.set_row(0, 24)
    details_sheet.set_row(1, 30)

    for pilot_row in interaction_summary_rows:
        pilot_name = str(pilot_row["pilot"]).replace("store_", "")
        pilot_users = [row for row in interaction_user_rows if row["pilot"] == pilot_row["pilot"]]
        pilot_users_sorted = sorted(
            pilot_users,
            key=lambda row: (-int(row["messages"]), -float(row["time_minutes"]), str(row["user_id"])),
        )
        sheet = workbook.add_worksheet(pilot_name[:31])
        sheet.write("A1", f"{pilot_row['pilot']} Interaction Users", title_format)
        sheet.write("A2", "Sorted by message count, then time spent.", note_format)
        write_sheet_table(
            workbook,
            sheet,
            pilot_users_sorted,
            detail_columns,
            f"{pilot_name.replace('-', '_')}Users",
            start_row=3,
        )
        sheet.set_row(0, 24)
        sheet.set_row(1, 24)
        top_n = min(len(pilot_users_sorted), 10)
        add_chart(
            workbook,
            sheet,
            sheet.get_name(),
            f"Top {top_n} Users by Messages",
            1,
            9,
            top_n,
            "M2",
            "Messages",
            start_row=4,
        )
        add_chart(
            workbook,
            sheet,
            sheet.get_name(),
            f"Top {top_n} Users by Time",
            1,
            10,
            top_n,
            "M21",
            "Time Minutes",
            start_row=4,
        )

    workbook.close()


def main() -> None:
    pilot_dirs = sorted(path for path in ROOT.iterdir() if path.is_dir() and path.name.startswith("store_Pilot_v"))
    global_user_lookup = build_global_user_lookup(pilot_dirs)
    analyses = [analyze_pilot(path, global_user_lookup) for path in pilot_dirs]

    summary_rows = [entry["summary"] for entry in analyses]
    user_rows = [row for entry in analyses for row in entry["users"]]
    interaction_summary_rows = [entry["interaction_summary"] for entry in analyses]
    interaction_user_rows = [row for entry in analyses for row in entry["interaction_users"]]

    write_csv(
        ROOT / "pilot_registered_user_summary.csv",
        summary_rows,
        [
            "pilot",
            "registered_users",
            "registered_non_admin_users",
            "active_registered_users_by_messages",
            "registered_user_messages",
            "registered_user_time_minutes",
            "registered_user_new_prompt_versions",
            "sessions_json_rows",
            "message_files_total_messages_all_users",
            "message_files_total_time_minutes_all_users",
            "new_prompt_versions_all_users",
            "orphaned_message_users",
            "orphaned_session_users",
            "orphaned_prompt_users",
        ],
    )
    write_csv(
        ROOT / "pilot_registered_user_details.csv",
        user_rows,
        [
            "pilot",
            "user_id",
            "display_name",
            "email",
            "is_admin",
            "registered",
            "sessions",
            "message_files",
            "messages",
            "time_minutes",
            "new_prompt_versions",
        ],
    )
    write_csv(
        ROOT / "pilot_interaction_user_summary.csv",
        interaction_summary_rows,
        [
            "pilot",
            "registered_users",
            "interaction_user_ids_total",
            "interaction_user_ids_registered_in_pilot",
            "interaction_user_ids_not_registered_in_pilot",
            "interaction_sessions",
            "interaction_messages",
            "interaction_time_minutes",
            "interaction_new_prompt_versions",
        ],
    )
    write_csv(
        ROOT / "pilot_interaction_user_details.csv",
        interaction_user_rows,
        [
            "pilot",
            "plot_label",
            "user_id",
            "display_name",
            "email",
            "is_admin",
            "registered_in_pilot",
            "sessions",
            "message_files",
            "messages",
            "time_minutes",
            "new_prompt_versions",
        ],
    )
    create_interaction_workbook(
        ROOT / "pilot_interaction_view_workbook.xlsx",
        interaction_summary_rows,
        interaction_user_rows,
    )

    with (ROOT / "pilot_registered_user_analysis.json").open("w", encoding="utf-8") as f:
        json.dump({"summary": summary_rows, "users": user_rows}, f, indent=2)
    with (ROOT / "pilot_interaction_user_analysis.json").open("w", encoding="utf-8") as f:
        json.dump({"summary": interaction_summary_rows, "users": interaction_user_rows}, f, indent=2)


if __name__ == "__main__":
    main()
