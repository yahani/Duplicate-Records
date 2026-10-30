import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import demo
import exporter

export = exporter.export_activities

# python3 -m unittest -v 2>&1 | tee test_results_before.txt
# python3 -m unittest -v 2>&1 | tee test_results_after.txt


class ExporterTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch('exporter.print_rows'))  # keep test output clean
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(demo.SCHEMA)
        self.conn.execute('INSERT INTO export_state (id, pointer) VALUES (1, ?)', (demo.INITIAL_POINTER,))

    def tearDown(self):
        self.conn.close()

    def start(self, activity_id, now):
        self.conn.execute('INSERT INTO activities (activity_id, start_time, updated_at) VALUES (?, ?, ?)',
                          (activity_id, now, now))

    def finish(self, activity_id, score, now):
        self.conn.execute('UPDATE activities SET finish_time = ?, score = ?, updated_at = ? WHERE activity_id = ?',
                          (now, score, now, activity_id))

    def correct(self, activity_id, now, start=None, score=None):
        if start is not None:
            self.conn.execute('UPDATE activities SET start_time = ? WHERE activity_id = ?', (start, activity_id))
        if score is not None:
            self.conn.execute('UPDATE activities SET score = ? WHERE activity_id = ?', (score, activity_id))
        self.conn.execute('UPDATE activities SET updated_at = ? WHERE activity_id = ?', (now, activity_id))

    def records(self, activity_id):
        return self.conn.execute('SELECT * FROM reported WHERE activity_id = ?', (activity_id,)).fetchall()

    def test_corrected_activity_is_reported_once_with_latest_values(self):
        self.start('A1', '2026-10-26 11:58:00')
        self.finish('A1', 3, '2026-10-26 12:02:00')
        export(self.conn, '2026-10-26 12:03:00')
        self.correct('A1', '2026-10-26 12:04:00', start='2026-10-26 11:57:00')
        export(self.conn, '2026-10-26 12:06:00')

        records = self.records('A1')
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['start_time'], '2026-10-26 11:57:00')

    def test_record_id_stays_the_same_across_repeated_corrections(self):
        self.start('A1', '2026-10-26 11:58:00')
        self.finish('A1', 3, '2026-10-26 12:02:00')
        export(self.conn, '2026-10-26 12:03:00')
        first_id = self.records('A1')[0]['record_id']
        for minute, start in [('04', '11:57'), ('07', '11:56'), ('10', '11:58')]:
            self.correct('A1', f'2026-10-26 12:{minute}:00', start=f'2026-10-26 {start}:00')
            export(self.conn, f'2026-10-26 12:{int(minute) + 1:02d}:00')

        self.assertEqual([r['record_id'] for r in self.records('A1')], [first_id])

    def test_different_activities_get_different_record_ids(self):
        self.start('A1', '2026-10-26 11:58:00')
        self.start('A2', '2026-10-26 11:58:00')
        self.finish('A1', 3, '2026-10-26 12:00:00')
        self.finish('A2', 4, '2026-10-26 12:00:00')
        export(self.conn, '2026-10-26 12:01:00')

        ids = [r['record_id'] for r in self.conn.execute('SELECT record_id FROM reported')]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)

    def test_record_id_is_the_same_in_a_separate_process(self):
        row = {'activity_id': 'A1', 'start_time': '2026-10-26 11:58:00'}
        script = f'import exporter; print(exporter.record_id({row!r}))'
        other = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, check=True,
                               cwd=Path(__file__).parent).stdout.strip()

        self.assertEqual(other, exporter.record_id(row))

    def test_score_correction_updates_the_existing_record(self):
        self.start('A1', '2026-10-26 11:58:00')
        self.finish('A1', 3, '2026-10-26 12:02:00')
        export(self.conn, '2026-10-26 12:03:00')
        self.correct('A1', '2026-10-26 12:04:00', score=5)
        export(self.conn, '2026-10-26 12:06:00')

        self.assertEqual([r['score'] for r in self.records('A1')], [5])

    def test_unchanged_activity_is_not_sent_again(self):
        self.start('A1', '2026-10-26 11:58:00')
        self.finish('A1', 3, '2026-10-26 12:02:00')
        export(self.conn, '2026-10-26 12:03:00')
        _, rows = export(self.conn, '2026-10-26 12:06:00')

        self.assertEqual(rows, [])


if __name__ == '__main__':
    unittest.main()
