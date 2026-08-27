import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from cell_api import CommandRunner, RailVoltages, ScanDebugCellAPI, ScanDebugConfig


class CommandRunnerPasswordSshTests(unittest.TestCase):
    def test_windows_password_ssh_uses_paramiko_and_combines_output(self) -> None:
        channel = Mock()
        channel.makefile.return_value.read.return_value = b"remote output\n"
        channel.recv_exit_status.return_value = 7
        transport = Mock()
        transport.is_active.return_value = True
        transport.open_session.return_value = channel
        client = Mock()
        client.get_transport.return_value = transport

        with patch("paramiko.SSHClient", return_value=client):
            result = CommandRunner._ssh_with_paramiko_password(
                "user@example.test",
                "secret",
                "hostname",
                timeout_s=30,
            )

        self.assertEqual(result.args, ["ssh", "user@example.test", "hostname"])
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout, "remote output\n")
        self.assertEqual(result.stderr, "")
        client.connect.assert_called_once_with(
            hostname="example.test",
            username="user",
            password="secret",
            timeout=30,
            banner_timeout=30,
            auth_timeout=30,
            allow_agent=False,
            look_for_keys=False,
        )
        channel.set_combine_stderr.assert_called_once_with(True)
        channel.exec_command.assert_called_once_with("hostname")
        channel.close.assert_called_once_with()
        client.close.assert_called_once_with()

    def test_windows_password_ssh_requires_user_at_hostname(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "user@hostname"):
            CommandRunner._ssh_with_paramiko_password("example.test", "secret", "hostname")


class CaptureCopyTests(unittest.TestCase):
    def test_remote_copy_falls_back_to_scp_when_rsync_is_not_on_path(self) -> None:
        with TemporaryDirectory() as temp_dir:
            api = ScanDebugCellAPI(
                ScanDebugConfig(
                    run_dir=Path(temp_dir),
                    saleae_host="user@example.test",
                    dry_run=True,
                )
            )
            api.runner = Mock()
            api.runner.run.return_value.returncode = 0
            api.runner.run.return_value.stdout = ""
            with patch("cell_api.shutil.which", side_effect=lambda name: None if name == "rsync" else "scp.exe"):
                local = api._copy_capture("/remote/capture", 3, "read", RailVoltages(1.0, 2.5))

            api.runner.run.assert_called_once_with(
                ["scp.exe", "-r", "user@example.test:/remote/capture/.", str(local)]
            )


class ReadRailDefaultTests(unittest.TestCase):
    def test_all_read_paths_share_half_volt_default(self) -> None:
        config = ScanDebugConfig()

        self.assertEqual(config.read_rails, RailVoltages(0.5, 2.5))


class SaleaeScriptUploadTests(unittest.TestCase):
    def test_matching_remote_script_skips_transfer(self) -> None:
        with TemporaryDirectory() as temp_dir:
            api = ScanDebugCellAPI(ScanDebugConfig(run_dir=Path(temp_dir), dry_run=False))
            api.runner = Mock()
            api._run_saleae = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))  # type: ignore[method-assign]

            api._write_remote_saleae_text("run_full_array_burst_capture.py", "script\n")

            api.runner.run.assert_not_called()
            self.assertIn("sha256sum", api._run_saleae.call_args.args[0])

    def test_changed_script_uses_scp_then_atomic_remote_install(self) -> None:
        with TemporaryDirectory() as temp_dir:
            api = ScanDebugCellAPI(ScanDebugConfig(run_dir=Path(temp_dir), dry_run=False))
            api._run_saleae = Mock(  # type: ignore[method-assign]
                side_effect=[
                    subprocess.CompletedProcess([], 1, "", ""),
                    subprocess.CompletedProcess([], 0, "", ""),
                ]
            )
            api.runner = Mock()

            def transfer(cmd: list[str], *, timeout_s: int | None = None) -> subprocess.CompletedProcess[str]:
                self.assertEqual(Path(cmd[-2]).read_bytes(), b"large script\n")
                return subprocess.CompletedProcess(cmd, 0, "", "")

            api.runner.run.side_effect = transfer
            with patch("cell_api.shutil.which", side_effect=lambda name: "scp.exe" if name == "scp" else None):
                api._write_remote_saleae_text("run_full_array_burst_capture.py", "large script\n")

            transfer_cmd = api.runner.run.call_args.args[0]
            self.assertEqual(transfer_cmd[0], "scp.exe")
            self.assertTrue(transfer_cmd[-1].startswith("ubuntu-24-04@100.98.132.51:/home/ubuntu-24-04/saleae-api/"))
            self.assertIn("chmod 755", api._run_saleae.call_args.args[0])
            self.assertIn("mv -f", api._run_saleae.call_args.args[0])


class HardwareQueueTests(unittest.TestCase):
    def test_acquire_accepts_verified_lock_after_ssh_return_timeout(self) -> None:
        with TemporaryDirectory() as temp_dir:
            api = ScanDebugCellAPI(ScanDebugConfig(run_dir=Path(temp_dir), dry_run=False))
            api.runner = Mock()
            api.runner.ssh.side_effect = [
                subprocess.TimeoutExpired(["ssh"], 20),
                subprocess.CompletedProcess(["ssh"], 0, "queue-token\n", ""),
            ]

            api._acquire_hardware_queue("user@example.test", "queue-token", "owner", "set")

            self.assertEqual(api.runner.ssh.call_count, 2)
            self.assertIn("/token", api.runner.ssh.call_args_list[1].args[1])


if __name__ == "__main__":
    unittest.main()
