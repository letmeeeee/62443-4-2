"""Isolated SSH handler tests; no Flask/device imports or real service commands."""
import ast
import subprocess
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


class SshApiTest(unittest.TestCase):
    def setUp(self):
        source = Path(__file__).parents[1] / "routes/route_g3.py"
        tree = ast.parse(source.read_text())
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and (node.name.startswith("_ssh_") or node.name in
                          ("get_ssh_status", "set_ssh_enabled"))]
        self.run = Mock()
        self.log = Mock()
        self.user = SimpleNamespace(current_user={"username": "admin", "permission": 4})
        self.request = SimpleNamespace(get_json=Mock(return_value={"enabled": True}))
        self.ns = {
            "subprocess": SimpleNamespace(run=self.run, TimeoutExpired=subprocess.TimeoutExpired),
            "g3_bp": SimpleNamespace(route=lambda *a, **kw: lambda function: function),
            "g": self.user, "request": self.request, "jsonify": lambda **kw: kw,
            "DPrint": Mock(), "SSH_CONTROL_LOCK": threading.Lock(),
            "SSH_SERVICE_UNITS": ("ssh.service", "sshd.service", "dropbear.service"),
            "config": SimpleNamespace(PERMISSION_TABLE={"usermanage": [4]}),
            "operationLog": SimpleNamespace(
                enqueue_operation_log=self.log,
                OperationType=SimpleNamespace(CONTROL="system.control"),
                OperationResult=SimpleNamespace(SUCCESS=1, FAIL=0)),
        }
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), self.ns)

    def completed(self, stdout="", rc=0, stderr=""):
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)

    def state(self, state="inactive", socket_state=None):
        return {"service": "ssh.service", "state": state,
                "socket": "ssh.socket" if socket_state is not None else None,
                "socketState": socket_state,
                "enabled": state == "active" or socket_state == "active"}

    def test_status_checks_service_and_socket(self):
        self.run.side_effect = [self.completed("LoadState=loaded\nActiveState=inactive"),
                                self.completed("LoadState=loaded\nActiveState=active")]
        body, code = self.ns["get_ssh_status"]()
        self.assertEqual(code, 200)
        self.assertTrue(body["enabled"])
        self.assertEqual(body["socketState"], "active")
        self.assertEqual(self.run.call_args.kwargs["timeout"], 15)

    def test_service_fallback_accepts_not_found_return_code(self):
        self.run.side_effect = [self.completed("LoadState=not-found", rc=4),
                                self.completed("LoadState=loaded\nActiveState=active"),
                                self.completed("LoadState=not-found", rc=4)]
        body, code = self.ns["get_ssh_status"]()
        self.assertEqual((code, body["service"]), (200, "sshd.service"))

    def test_no_service_is_error(self):
        self.run.return_value = self.completed("LoadState=not-found", rc=4)
        self.assertEqual(self.ns["get_ssh_status"]()[1], 503)

    def test_missing_state_is_error(self):
        self.run.return_value = self.completed("LoadState=loaded")
        self.assertEqual(self.ns["get_ssh_status"]()[1], 503)

    def test_anonymous_cannot_query_or_control(self):
        self.user.current_user = None
        self.assertEqual(self.ns["get_ssh_status"]()[1], 401)
        self.assertEqual(self.ns["set_ssh_enabled"]()[1], 401)
        self.run.assert_not_called()

    def test_non_admin_cannot_control_or_spoof_identity(self):
        self.user.current_user = {"username": "viewer", "permission": 1}
        self.request.get_json.return_value = {"enabled": True, "operatorName": "admin"}
        self.assertEqual(self.ns["set_ssh_enabled"]()[1], 403)
        self.run.assert_not_called()
        self.assertEqual(self.log.call_args.args[0], "viewer")

    def test_invalid_bodies_never_run_commands(self):
        for body in (None, [], {}, {"enabled": 1}, {"enabled": "false"}, {"enabled": None}):
            with self.subTest(body=body):
                self.request.get_json.return_value = body
                self.assertEqual(self.ns["set_ssh_enabled"]()[1], 400)
        self.run.assert_not_called()

    def test_enable_and_audit_authenticated_user(self):
        self.ns["_ssh_status"] = Mock(side_effect=[self.state(), self.state("active")])
        self.run.return_value = self.completed()
        self.request.get_json.return_value = {"enabled": True, "operatorName": "spoofed"}
        body, code = self.ns["set_ssh_enabled"]()
        self.assertEqual((code, body["enabled"]), (200, True))
        self.assertEqual(self.run.call_args.args[0],
                         ["systemctl", "--no-ask-password", "start", "ssh.service"])
        self.assertEqual(self.log.call_args.args, ("admin", "system.control", "SSH", 1, 1))

    def test_disable_stops_socket_before_service(self):
        self.request.get_json.return_value = {"enabled": False}
        self.ns["_ssh_status"] = Mock(side_effect=[self.state("active", "active"),
                                                  self.state("inactive", "inactive")])
        self.run.return_value = self.completed()
        self.assertEqual(self.ns["set_ssh_enabled"]()[1], 200)
        self.assertEqual([call.args[0][-2:] for call in self.run.call_args_list],
                         [["stop", "ssh.socket"], ["stop", "ssh.service"]])

    def test_unsettled_state_does_not_report_success(self):
        self.ns["_ssh_status"] = Mock(side_effect=[self.state(), self.state("activating")])
        self.run.return_value = self.completed()
        self.assertEqual(self.ns["set_ssh_enabled"]()[1], 503)
        self.assertEqual(self.log.call_args.args[-1], 0)

    def test_failed_commands_are_audited(self):
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("systemctl", 15),
                      RuntimeError("permission denied")):
            with self.subTest(error=error):
                self.ns["_ssh_status"] = Mock(side_effect=error)
                self.assertEqual(self.ns["set_ssh_enabled"]()[1], 503)
                self.assertEqual(self.log.call_args.args[-1], 0)

    def test_nonzero_exit_is_error(self):
        self.run.return_value = self.completed(rc=1, stderr="Access denied")
        self.assertEqual(self.ns["get_ssh_status"]()[1], 503)


if __name__ == "__main__":
    unittest.main()
