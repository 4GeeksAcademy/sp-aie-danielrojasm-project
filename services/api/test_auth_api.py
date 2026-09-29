import os
import tempfile
import unittest
from datetime import timedelta

from fastapi.testclient import TestClient
from tinydb import Query

from services.api.auth_models import UserRole, UserUpdate
from services.api.database import get_auth_db
from services.api.main import app
from services.api.security import create_access_token
from services.api.user_service import get_profile_by_user_id, update_user


class AuthApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        os.environ["AUTH_DB_PATH"] = os.path.join(
            self.temp_directory.name, "auth.json"
        )
        os.environ["JWT_SECRET_KEY"] = "test-secret-key-with-at-least-32-characters"
        os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "30"
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp_directory.cleanup()
        for variable in (
            "AUTH_DB_PATH",
            "JWT_SECRET_KEY",
            "ACCESS_TOKEN_EXPIRE_MINUTES",
        ):
            os.environ.pop(variable, None)

    def register(
        self,
        email: str = "owner@example.com",
        password: str = "correct-password",
    ) -> dict[str, object]:
        response = self.client.post(
            "/users",
            json={
                "email": email,
                "password": password,
                "name": "Owner",
                "phone": "+1 555 0100",
                "address": "Los Angeles",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def login(
        self,
        email: str = "owner@example.com",
        password: str = "correct-password",
    ) -> str:
        response = self.client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["access_token"]

    @staticmethod
    def authorization(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_registration_hashes_password_and_creates_profile(self) -> None:
        user = self.register()

        self.assertNotIn("password", user)
        self.assertNotIn("hashed_password", user)
        self.assertEqual(user["role"], "user")
        with get_auth_db() as db:
            stored_user = db.table("users").get(Query().id == user["id"])
            profiles = db.table("profiles").search(Query().user_id == user["id"])
        self.assertIsNotNone(stored_user)
        self.assertNotEqual(stored_user["hashed_password"], "correct-password")
        self.assertTrue(stored_user["hashed_password"].startswith("$2"))
        self.assertEqual(len(profiles), 1)
        self.assertEqual(profiles[0]["name"], "Owner")

    def test_login_supports_json_and_oauth2_form(self) -> None:
        self.register()

        json_token = self.login()
        form_response = self.client.post(
            "/auth/login",
            data={"username": "owner@example.com", "password": "correct-password"},
        )

        self.assertTrue(json_token)
        self.assertEqual(form_response.status_code, 200, form_response.text)
        self.assertEqual(form_response.json()["token_type"], "bearer")

    def test_auth_me_and_profile_update_return_linked_profile(self) -> None:
        user = self.register()
        headers = self.authorization(self.login())

        update_response = self.client.put(
            "/profiles/me",
            headers=headers,
            json={"name": "Updated", "phone": "555", "address": "Zaragoza"},
        )
        me_response = self.client.get("/auth/me", headers=headers)

        self.assertEqual(update_response.status_code, 200, update_response.text)
        self.assertEqual(me_response.status_code, 200, me_response.text)
        self.assertEqual(me_response.json()["email"], "owner@example.com")
        self.assertEqual(me_response.json()["profile"]["user_id"], user["id"])
        self.assertEqual(me_response.json()["profile"]["name"], "Updated")

    def test_invalid_malformed_and_expired_tokens_return_401(self) -> None:
        user = self.register()
        expired_token = create_access_token(
            str(user["id"]), expires_delta=timedelta(minutes=-1)
        )

        no_token = self.client.get("/auth/me")
        malformed = self.client.get(
            "/auth/me", headers=self.authorization("not-a-jwt")
        )
        expired = self.client.get(
            "/auth/me", headers=self.authorization(expired_token)
        )

        self.assertEqual(no_token.status_code, 401)
        self.assertEqual(malformed.status_code, 401)
        self.assertEqual(expired.status_code, 401)

    def test_existing_sensitive_routes_require_authentication(self) -> None:
        requests = (
            ("get", "/suppliers", None),
            ("post", "/suppliers", {}),
            ("get", "/suppliers/1", None),
            ("patch", "/suppliers/1/rate", {}),
            ("patch", "/suppliers/1/status", {}),
            ("delete", "/suppliers/1", None),
            ("post", "/api/incidents/analyze", None),
            ("get", "/api/incidents/results/export", None),
        )

        for method, path, json_body in requests:
            with self.subTest(method=method, path=path):
                response = self.client.request(method, path, json=json_body)
                self.assertEqual(response.status_code, 401, response.text)

        self.register()
        headers = self.authorization(self.login())
        authenticated_requests = (
            ("get", "/suppliers", None),
            ("post", "/suppliers", {}),
            ("get", "/suppliers/1", None),
            ("patch", "/suppliers/1/rate", {}),
            ("patch", "/suppliers/1/status", {}),
            ("delete", "/suppliers/1", None),
            ("post", "/api/incidents/analyze", None),
            ("get", "/api/incidents/results/export", None),
        )
        for method, path, json_body in authenticated_requests:
            with self.subTest(authenticated_method=method, authenticated_path=path):
                response = self.client.request(
                    method, path, headers=headers, json=json_body
                )
                self.assertNotEqual(response.status_code, 401, response.text)

    def test_user_cannot_read_update_or_delete_another_user(self) -> None:
        first_user = self.register()
        second_user = self.register("second@example.com")
        headers = self.authorization(self.login())

        read_response = self.client.get(
            f"/users/{second_user['id']}", headers=headers
        )
        update_response = self.client.put(
            f"/users/{second_user['id']}",
            headers=headers,
            json={"email": "stolen@example.com"},
        )
        delete_response = self.client.delete(
            f"/users/{second_user['id']}", headers=headers
        )

        self.assertNotEqual(first_user["id"], second_user["id"])
        self.assertEqual(read_response.status_code, 403)
        self.assertEqual(update_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)

    def test_only_admin_can_change_roles(self) -> None:
        admin = self.register("admin@example.com")
        target = self.register("target@example.com")
        regular_headers = self.authorization(self.login("admin@example.com"))
        denied_list = self.client.get("/users", headers=regular_headers)
        denied = self.client.put(
            f"/users/{admin['id']}",
            headers=regular_headers,
            json={"role": "admin"},
        )
        self.assertEqual(denied_list.status_code, 403)
        self.assertEqual(denied.status_code, 403)

        update_user(str(admin["id"]), UserUpdate(role=UserRole.ADMIN))
        admin_headers = self.authorization(self.login("admin@example.com"))
        allowed = self.client.put(
            f"/users/{target['id']}",
            headers=admin_headers,
            json={"role": "manager"},
        )
        allowed_list = self.client.get("/users", headers=admin_headers)

        self.assertEqual(allowed.status_code, 200, allowed.text)
        self.assertEqual(allowed.json()["role"], "manager")
        self.assertEqual(allowed_list.status_code, 200, allowed_list.text)
        self.assertEqual(len(allowed_list.json()), 2)

    def test_user_update_and_delete_cascade(self) -> None:
        user = self.register()
        headers = self.authorization(self.login())
        updated = self.client.put(
            f"/users/{user['id']}",
            headers=headers,
            json={"email": "new@example.com", "password": "new-password"},
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.login("new@example.com", "new-password")

        deleted = self.client.delete(f"/users/{user['id']}", headers=headers)

        self.assertEqual(deleted.status_code, 204, deleted.text)
        self.assertIsNone(get_profile_by_user_id(str(user["id"])))
        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 401)

    def test_role_validation_and_duplicate_email(self) -> None:
        user = self.register()
        duplicate = self.client.post(
            "/users",
            json={"email": "owner@example.com", "password": "another-password"},
        )
        headers = self.authorization(self.login())
        invalid_role = self.client.put(
            f"/users/{user['id']}", headers=headers, json={"role": "superuser"}
        )

        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(invalid_role.status_code, 422)


if __name__ == "__main__":
    unittest.main()