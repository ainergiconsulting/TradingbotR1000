from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from current_reference.PaperTradingR1000.massive_historical_downloader import EXPECTED_SCHEMA, UniverseEntry
from tools.resume_massive_history import download_targets


class FakeMassiveClient:
    def get_daily_aggregates(self, symbol, start_date, end_date, *, adjusted):
        return (
            [
                {"t": 1704153600000, "o": 10.0, "h": 11.0, "l": 9.0, "c": 10.5, "v": 1000, "n": 10, "vw": 10.25},
                {"t": 1704240000000, "o": 10.5, "h": 12.0, "l": 10.0, "c": 11.5, "v": 1200, "n": 12, "vw": 11.25},
            ],
            1,
        )


class ResumeMassiveHistoryTests(unittest.TestCase):
    def test_download_updates_symbol_checkpoint_without_full_checkpoint_rewrite(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            args = SimpleNamespace(
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
                adjusted=False,
                daily_bars_dir=root / "daily_bars",
                resume_progress_file=root / "massive_resume_progress.json",
                failed_report_file=root / "massive_resume_failed_symbols.csv",
                log_file=root / "massive_resume.log",
                checkpoint_file=root / "historical_bars.massive_checkpoint.csv",
            )
            entry = UniverseEntry("AAA", "AAA", "AAA INC", "NYSE", "USD", "Industrials")

            rows, results = download_targets(
                FakeMassiveClient(),
                ["AAA"],
                {"AAA": entry},
                [],
                EXPECTED_SCHEMA,
                args,
                set(),
                {},
            )

            self.assertEqual(rows, [])
            self.assertFalse(args.checkpoint_file.exists())
            self.assertEqual(results[0].status, "ok")
            self.assertTrue((args.daily_bars_dir / "AAA.csv").exists())
            progress = json.loads(args.resume_progress_file.read_text(encoding="utf-8"))
            self.assertEqual(progress["completed_symbols"], ["AAA"])
            self.assertIn("full_checkpoint_rewrite", args.log_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
