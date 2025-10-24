import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.web.server import create_app, reset_services


class WebInterfaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.temp_db_path = os.path.join(self.temp_dir, "users.json")
        with open(self.temp_db_path, "w", encoding="utf-8") as fh:
            fh.write("{}")
        os.environ["USBUTLER_USERS_DB"] = self.temp_db_path
        os.environ["USBUTLER_WEB_ENABLE_READER"] = "1"
        self.reader_state_path = os.path.join(self.temp_dir, "reader_state.json")
        os.environ["USBUTLER_READER_STATE_FILE"] = self.reader_state_path
        reset_services(self.temp_db_path)
        self.client = create_app().test_client()

    def tearDown(self) -> None:
        os.environ.pop("USBUTLER_USERS_DB", None)
        os.environ.pop("USBUTLER_WEB_ENABLE_READER", None)
        os.environ.pop("USBUTLER_READER_STATE_FILE", None)
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_index_page_renders(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Registered Users", response.data)

    def test_reader_claim_and_release(self) -> None:
        initial = self.client.get("/api/reader")
        self.assertEqual(initial.status_code, 200)
        initial_body = json.loads(initial.data)
        self.assertTrue(initial_body["success"])
        self.assertEqual(initial_body["state"]["owner"], "door")

        claim = self.client.post("/api/reader/claim")
        self.assertEqual(claim.status_code, 200)
        claim_body = json.loads(claim.data)
        self.assertTrue(claim_body["success"])
        self.assertEqual(claim_body["state"]["owner"], "web")

        release = self.client.post("/api/reader/release")
        self.assertEqual(release.status_code, 200)
        release_body = json.loads(release.data)
        self.assertTrue(release_body["success"])
        self.assertEqual(release_body["state"]["owner"], "door")

    def test_add_user_flow(self) -> None:
        payload = {"identifier": "12345678", "name": "Test User", "access_level": "user"}
        response = self.client.post("/api/users", json=payload)
        self.assertEqual(response.status_code, 201)
        body = json.loads(response.data)
        self.assertTrue(body["success"])
        self.assertEqual(body["user"]["primary_identifier"]["value"], "12345678")

        duplicate_response = self.client.post("/api/users", json=payload)
        self.assertEqual(duplicate_response.status_code, 409)

    def test_toggle_and_remove_user(self) -> None:
        payload = {"identifier": "87654321", "name": "Another User", "access_level": "admin"}
        creation = self.client.post("/api/users", json=payload)
        user_body = json.loads(creation.data)
        user_id = user_body["user"]["user_id"]

        toggle_resp = self.client.post(f"/api/users/{user_id}/toggle")
        self.assertEqual(toggle_resp.status_code, 200)
        body = json.loads(toggle_resp.data)
        self.assertFalse(body["user"]["active"])

        delete_resp = self.client.delete(f"/api/users/{user_id}")
        self.assertEqual(delete_resp.status_code, 200)

    def test_attach_identifier_to_existing_user(self) -> None:
        creation = self.client.post(
            "/api/users",
            json={"identifier": "1111", "name": "Primary User", "access_level": "user"},
        )
        body = json.loads(creation.data)
        user_id = body["user"]["user_id"]

        attach = self.client.post(
            "/api/users",
            json={
                "identifier": "AAAA",
                "identifier_type": "UID",
                "user_id": user_id,
                "make_primary": True,
            },
        )
        self.assertEqual(attach.status_code, 200)
        attach_body = json.loads(attach.data)
        self.assertTrue(attach_body["success"])
        identifiers = attach_body["user"]["identifiers"]
        self.assertEqual(len(identifiers), 2)
        primary = next(item for item in identifiers if item["primary"])
        self.assertEqual(primary["value"], "AAAA")

    def test_scan_card_timeout(self) -> None:
        self.client.post("/api/reader/claim")
        with patch("app.web.server._emv_service") as emv_mock:
            emv_mock.wait_for_card.return_value = False
            response = self.client.post("/api/scan-card", json={"timeout": 1})
            self.assertEqual(response.status_code, 200)
            body = json.loads(response.data)
            self.assertFalse(body["success"])
            self.assertEqual(body["error"], "timeout")

    def test_scan_card_success(self) -> None:
        fake_scan = MagicMock()
        fake_scan.primary_identifier.return_value = "ABCDEF"
        fake_scan.primary_identifier_type.return_value = "UID"
        fake_scan.tag_type = "Type4"
        fake_scan.card_type = "ISO"
        fake_scan.uid = "ABCDEF"
        fake_scan.pan = None
        fake_scan.tokenized = False

        self.client.post("/api/reader/claim")
        with patch("app.web.server._emv_service") as emv_mock:
            emv_mock.wait_for_card.return_value = True
            emv_mock.read_card_data.return_value = fake_scan
            response = self.client.post("/api/scan-card", json={"timeout": 1})
            self.assertEqual(response.status_code, 200)
            body = json.loads(response.data)
            self.assertTrue(body["success"])
            self.assertEqual(body["identifier"], "ABCDEF")
            self.assertIn("masked_identifier", body)
            self.assertFalse(body["already_registered"])
            emv_mock.disconnect.assert_called()

    def test_scan_card_detects_existing_user(self) -> None:
        # Pre-populate a user in the DB
        creation = self.client.post(
            "/api/users",
            json={"identifier": "5555", "name": "Collide", "access_level": "user"},
        )
        self.assertEqual(creation.status_code, 201)

        fake_scan = MagicMock()
        fake_scan.primary_identifier.return_value = "5555"
        fake_scan.primary_identifier_type.return_value = "UID"
        fake_scan.tag_type = "Type4"
        fake_scan.card_type = "ISO"
        fake_scan.uid = "5555"
        fake_scan.pan = None
        fake_scan.tokenized = False

        self.client.post("/api/reader/claim")
        with patch("app.web.server._emv_service") as emv_mock:
            emv_mock.wait_for_card.return_value = True
            emv_mock.read_card_data.return_value = fake_scan
            response = self.client.post("/api/scan-card", json={"timeout": 1})
            body = json.loads(response.data)
            self.assertTrue(body["already_registered"])
            self.assertEqual(body["existing_user"]["name"], "Collide")

    def test_pause_and_resume_user(self) -> None:
        creation = self.client.post(
            "/api/users",
            json={"identifier": "P123", "name": "Pausable", "access_level": "user"},
        )
        self.assertEqual(creation.status_code, 201)
        created = json.loads(creation.data)
        user_id = created["user"]["user_id"]
        self.assertTrue(created["user"]["active"])

        pause_resp = self.client.post(f"/api/users/{user_id}/pause")
        self.assertEqual(pause_resp.status_code, 200)
        paused = json.loads(pause_resp.data)
        self.assertFalse(paused["user"]["active"])

        resume_resp = self.client.post(f"/api/users/{user_id}/resume")
        self.assertEqual(resume_resp.status_code, 200)
        resumed = json.loads(resume_resp.data)
        self.assertTrue(resumed["user"]["active"])

    def test_get_user_by_identifier(self) -> None:
        creation = self.client.post(
            "/api/users",
            json={"identifier": "LOOKUP1", "name": "Lookup", "access_level": "admin"},
        )
        self.assertEqual(creation.status_code, 201)

        success = self.client.get("/api/users/by-identifier/LOOKUP1")
        self.assertEqual(success.status_code, 200)
        body = json.loads(success.data)
        self.assertTrue(body["success"])
        self.assertEqual(body["user"]["name"], "Lookup")

        missing = self.client.get("/api/users/by-identifier/NON_EXISTENT")
        self.assertEqual(missing.status_code, 404)


if __name__ == "__main__":
    unittest.main()
