import datetime
import os
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "kaggle-kernel-watch.sh"


class KaggleKernelWatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="kaggle-kernel-watch-"))
        self.log = self.tmp / "watch.log"
        self.fake = self.tmp / "kaggle"
        self.fake.write_text(
            "#!/usr/bin/env bash\n"
            "if [ \"$1\" = kernels ] && [ \"$2\" = status ]; then\n"
            "  echo 'kernel has status \"KernelWorkerStatus.RUNNING\"'\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$1\" = kernels ] && [ \"$2\" = list ]; then\n"
            "  echo 'Warning: outdated kaggle version'\n"
            "  echo 'ref,title,author,lastRunTime,totalVotes'\n"
            "  echo \"owner/kernel,Kernel,Owner,$FAKE_LAST_RUN,0\"\n"
            "  exit 0\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        self.fake.chmod(0o755)

    def run_watch(self, last_run, max_min=720):
        env = os.environ.copy()
        env["FAKE_LAST_RUN"] = last_run
        env["KAGGLE_WATCH_LOG"] = str(self.log)
        return subprocess.run(
            [
                str(SCRIPT),
                "--slug", "owner/kernel",
                "--out", str(self.tmp / "out"),
                "--interval", "1",
                "--max-min", str(max_min),
                "--once",
                "--kaggle-bin", str(self.fake),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def test_once_reports_elapsed_and_remaining_from_kernel_start(self):
        started = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=60)
        result = self.run_watch(started.strftime("%Y-%m-%d %H:%M:%S.000000"))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        text = self.log.read_text(encoding="utf-8")
        self.assertIn("status=RUNNING", text)
        self.assertIn("start_source=lastRunTime", text)
        self.assertRegex(text, r"elapsed_min=(59|60)")
        self.assertRegex(text, r"remaining_min=(659|660)")
        self.assertIn("once=true", text)

    def test_deadline_uses_kernel_start_not_watcher_start(self):
        started = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=20)
        result = self.run_watch(started.strftime("%Y-%m-%d %H:%M:%S.000000"), max_min=10)
        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        text = self.log.read_text(encoding="utf-8")
        self.assertIn("timeout: 10min sem completar desde lastRunTime", text)
        self.assertIn("status=RUNNING", text)


if __name__ == "__main__":
    unittest.main()
