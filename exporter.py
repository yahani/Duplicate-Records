import uuid

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
