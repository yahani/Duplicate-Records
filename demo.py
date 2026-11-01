"""Activity reporting demo.

Sends finished activities to the `reported` table (a stand-in for an external
reporting system). Changed activities are sent again so the reporting system
always has the latest version. Every command takes a fake clock via --now.

    python3 demo.py start A1 --now "2026-10-26 11:58"
    python3 demo.py finish A1 3 --now "2026-10-26 12:02"
    python3 demo.py correct A1 --start "2026-10-26 11:57" --now "2026-10-26 12:04"
    python3 demo.py export --now "2026-10-26 12:06"
    python3 demo.py show
    python3 demo.py duplicates
    python3 demo.py reset
"""
import argparse
import uuid
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).with_name('activities.db')
TIME_FORMAT = '%Y-%m-%d %H:%M:%S'
INITIAL_POINTER = '2026-10-26 00:00:00'

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    activity_id TEXT PRIMARY KEY,
    start_time  TEXT NOT NULL,
    finish_time TEXT,
    score       INTEGER,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reported (
    record_id   TEXT PRIMARY KEY,
    activity_id TEXT NOT NULL,
    start_time  TEXT NOT NULL,
    finish_time TEXT NOT NULL,
    score       INTEGER,
    reported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS export_state (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    pointer TEXT NOT NULL
);
"""

RECORD_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, 'https://example.com/reporting/records')


def record_id(row):
    return str(uuid.uuid5(RECORD_NAMESPACE, f"{row['activity_id']}|{row['start_time']}"))


def export_activities(conn, now):
    pointer_before = get_pointer(conn)
    rows = conn.execute(
        """
        SELECT * FROM activities
        WHERE finish_time IS NOT NULL AND updated_at > ? AND updated_at <= ?
        ORDER BY updated_at
        """,
        (pointer_before, now),
    ).fetchall()
    print_rows(f'Changed finished rows ({pointer_before} < updated_at <= {now})', rows,
               ['activity_id', 'start_time', 'finish_time', 'score', 'updated_at'])

    for row in rows:
        conn.execute(
            'INSERT OR REPLACE INTO reported (record_id, activity_id, start_time, finish_time, score, reported_at) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            (record_id(row), row['activity_id'], row['start_time'], row['finish_time'], row['score'], now),
        )
    set_pointer(conn, now)
    conn.commit()
    return pointer_before, rows


def get_pointer(conn):
    return conn.execute('SELECT pointer FROM export_state WHERE id = 1').fetchone()['pointer']


def set_pointer(conn, pointer):
    conn.execute('UPDATE export_state SET pointer = ? WHERE id = 1', (pointer,))


def print_rows(title, rows, columns):
    print(f'\n{title}')
    if not rows:
        print('  (none)')
        return
    values = [[('NULL' if row[c] is None else str(row[c])) for c in columns] for row in rows]
    widths = [max(len(c), *(len(v[i]) for v in values)) for i, c in enumerate(columns)]
    print('  ' + '  '.join(c.ljust(w) for c, w in zip(columns, widths)))
    print('  ' + '  '.join('-' * w for w in widths))
    for v in values:
        print('  ' + '  '.join(x.ljust(w) for x, w in zip(v, widths)))


# --- helpers -----------------------------------------------------------------

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.execute('INSERT OR IGNORE INTO export_state (id, pointer) VALUES (1, ?)', (INITIAL_POINTER,))
    conn.commit()
    return conn


def parse_time(value):
    """Accept 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD HH:MM:SS'; return 'YYYY-MM-DD HH:MM:SS'."""
    for fmt in (TIME_FORMAT, '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(value, fmt).strftime(TIME_FORMAT)
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(f'bad time {value!r}, expected "YYYY-MM-DD HH:MM[:SS]"')


def get_activity(conn, activity_id):
    row = conn.execute('SELECT * FROM activities WHERE activity_id = ?', (activity_id,)).fetchone()
    if row is None:
        sys.exit(f'activity {activity_id} does not exist')
    return row


# --- commands ----------------------------------------------------------------

def cmd_start(conn, args):
    try:
        conn.execute('INSERT INTO activities (activity_id, start_time, updated_at) VALUES (?, ?, ?)',
                     (args.activity_id, args.now, args.now))
    except sqlite3.IntegrityError:
        sys.exit(f'activity {args.activity_id} already exists')
    conn.commit()
    print(f'[{args.now}] {args.activity_id} started')


def cmd_finish(conn, args):
    row = get_activity(conn, args.activity_id)
    if row['finish_time'] is not None:
        sys.exit(f'activity {args.activity_id} already finished at {row["finish_time"]}')
    conn.execute('UPDATE activities SET finish_time = ?, score = ?, updated_at = ? WHERE activity_id = ?',
                 (args.now, args.score, args.now, args.activity_id))
    conn.commit()
    print(f'[{args.now}] {args.activity_id} finished with score {args.score}')


def cmd_correct(conn, args):
    row = get_activity(conn, args.activity_id)
    if args.start is None and args.score is None:
        sys.exit('nothing to correct: pass --start and/or --score')
    start_time = args.start or row['start_time']
    score = row['score'] if args.score is None else args.score
    conn.execute('UPDATE activities SET start_time = ?, score = ?, updated_at = ? WHERE activity_id = ?',
                 (start_time, score, args.now, args.activity_id))
    conn.commit()
    print(f'[{args.now}] {args.activity_id} corrected: start {row["start_time"]} -> {start_time}, '
          f'score {row["score"]} -> {score}')


def cmd_export(conn, args):
    print(f'=== export run at {args.now} ===')
    pointer_before, sent = export_activities(conn, args.now)
    print(f'\nSent:    {", ".join(r["activity_id"] for r in sent) or "nothing"}')
    print(f'Pointer: {pointer_before} -> {get_pointer(conn)}')


def cmd_show(conn, args):
    print_rows('activities', conn.execute('SELECT * FROM activities ORDER BY activity_id').fetchall(),
               ['activity_id', 'start_time', 'finish_time', 'score', 'updated_at'])
    print_rows('reported', conn.execute('SELECT * FROM reported ORDER BY activity_id, reported_at').fetchall(),
               ['record_id', 'activity_id', 'start_time', 'score', 'reported_at'])
    print(f'\nexport_state.pointer = {get_pointer(conn)}')


def cmd_duplicates(conn, args):
    rows = conn.execute(
        """
        SELECT * FROM reported
        WHERE activity_id IN (SELECT activity_id FROM reported GROUP BY activity_id HAVING COUNT(*) > 1)
        ORDER BY activity_id, reported_at
        """
    ).fetchall()
    print_rows('Activities with more than one record in the reporting system', rows,
               ['record_id', 'activity_id', 'start_time', 'score', 'reported_at'])


def cmd_reset(conn, args):
    conn.execute('DELETE FROM activities')
    conn.execute('DELETE FROM reported')
    set_pointer(conn, INITIAL_POINTER)
    conn.commit()
    print(f'reset: tables emptied, pointer = {INITIAL_POINTER}')


# --- CLI ---------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(description='Activity reporting demo')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('start', help='an activity starts')
    p.add_argument('activity_id')
    p.add_argument('--now', type=parse_time, required=True)
    p.set_defaults(func=cmd_start)

    p = sub.add_parser('finish', help='an activity finishes')
    p.add_argument('activity_id')
    p.add_argument('score', type=int)
    p.add_argument('--now', type=parse_time, required=True)
    p.set_defaults(func=cmd_finish)

    p = sub.add_parser('correct', help='correct an activity\'s start time and/or score')
    p.add_argument('activity_id')
    p.add_argument('--start', type=parse_time)
    p.add_argument('--score', type=int)
    p.add_argument('--now', type=parse_time, required=True)
    p.set_defaults(func=cmd_correct)

    p = sub.add_parser('export', help='run the exporter once')
    p.add_argument('--now', type=parse_time, required=True)
    p.set_defaults(func=cmd_export)

    sub.add_parser('show', help='print all tables').set_defaults(func=cmd_show)
    sub.add_parser('duplicates', help='activities with more than one record').set_defaults(func=cmd_duplicates)
    sub.add_parser('reset', help='empty tables and reset the pointer').set_defaults(func=cmd_reset)
    return parser


def main():
    args = build_parser().parse_args()
    conn = connect()
    try:
        args.func(conn, args)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
