import os
import json
import requests
import sys
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    NEXTJS_API_URL,
)

# Determine the base path whether running as script or bundled with PyInstaller
if getattr(sys, "frozen", False):
    # PyInstaller: sys.executable is the path to the bundled app
    base_path = Path(sys.executable).parent
else:
    # Normal Python execution
    base_path = Path(__file__).resolve().parent


class GoogleAuthenticator:
    def __init__(self):
        self.curr_dir = Path(__file__).parent
        self.client_id = GOOGLE_CLIENT_ID
        self.client_secret = GOOGLE_CLIENT_SECRET
        self.scopes = [
            "openid",
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
        ]
        self.nextjs_api_url = NEXTJS_API_URL
        self.token_file = self.curr_dir.joinpath("google_token.json")
        self.credentials = None
        self.user_info = None
        self.redirect_port = 8080  # Fixed port for OAuth

    def load_saved_credentials(self):
        """Load previously saved credentials if they exist (without storing client secrets)"""
        if self.token_file.exists():
            token_data = json.loads(self.token_file.read_text())

            # Inject client_id and client_secret temporarily
            token_data["client_id"] = self.client_id
            token_data["client_secret"] = self.client_secret

            try:
                self.credentials = Credentials.from_authorized_user_info(token_data)

                # Refresh if expired
                if self.credentials and self.credentials.expired and self.credentials.refresh_token:
                    self.credentials.refresh(Request())
                    self.save_credentials()  # Save refreshed tokens
                return True
            except Exception as e:
                print("Failed to load saved credentials:", e)
        return False

    def save_credentials(self):
        """Save OAuth credentials securely (without client secrets)"""
        if self.credentials:
            token_data = {
                "token": self.credentials.token,
                "refresh_token": self.credentials.refresh_token,
                "token_uri": self.credentials.token_uri,
                "scopes": self.credentials.scopes,
                "expiry": self.credentials.expiry.isoformat(),
            }
            self.token_file.write_text(json.dumps(token_data, indent=4, separators=(",", ": ")))

    def authenticate(self):
        """Authenticate user with Google OAuth"""
        if self.load_saved_credentials():
            print("Loaded existing credentials")
            return self.get_user_info()

        # Set up the OAuth flow using environment variables
        flow = InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
                }
            },
            self.scopes,
        )

        # Try multiple ports in case one is blocked
        for port in [8080, 8765, 5000]:
            try:
                print(f"Trying to open local server on http://localhost:{port} ...")
                self.credentials = flow.run_local_server(port=port)
                print(f"Successfully authenticated via localhost:{port}")
                self.save_credentials()
                return self.get_user_info()
            except OSError as e:
                print(f"Port {port} failed: {e}")

        # If all ports failed, fallback to console
        print("⚠️ Failed to open local web server. Falling back to manual login.")
        self.credentials = flow.run_console()
        self.save_credentials()
        return self.get_user_info()

    def get_user_info(self):
        """Retrieve user information from Google"""
        if not self.credentials:
            return None

        response = requests.get(
            "https://www.googleapis.com/oauth2/v1/userinfo",
            headers={"Authorization": f"Bearer {self.credentials.token}"},
        )

        if response.status_code == 200:
            self.user_info = response.json()
            return self.user_info
        return None

    def verify_with_nextjs(self):
        """Verify the Google token with Next.js backend"""
        if not self.credentials or not self.user_info:
            return False

        try:
            email = self.user_info.get("email")
            if not email:
                print("Error: No email found in user info")
                return None

            print(f"Token sent to Next.js: {self.credentials.token[:20]}...")

            response = requests.post(
                f"{self.nextjs_api_url}/auth/verify-token",
                json={
                    "token": self.credentials.token,
                    "provider": "google",
                    "email": email,
                },
                headers={"Content-Type": "application/json"},
            )

            if response.status_code == 200:
                result = response.json()
                return result
            else:
                print(f"Error verifying with Next.js: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"Error communicating with Next.js: {e}")
            return None

    def logout(self):
        """Clear saved credentials securely"""
        if self.token_file.exists():
            self.token_file.unlink()

        self.credentials = None
        self.user_info = None
        print("Logged out successfully.")


def main():
    auth = GoogleAuthenticator()

    # Authenticate user
    user_info = auth.authenticate()

    if user_info:
        print(f"Authenticated as: {user_info.get('email')}")
        print(f"Name: {user_info.get('name')}")

        # Verify with Next.js backend
        next_auth = auth.verify_with_nextjs()
        if next_auth:
            print("Verified with Next.js backend")
            print(f"User role: {next_auth.get('user', {}).get('role', 'unknown')}")
            print(f"Next.js token: {next_auth.get('token')}")
            return True, next_auth.get("token")
        else:
            print("Failed to verify with Next.js backend")
            return False, None
    else:
        print("Authentication failed")
        if auth.token_file.exists():
            auth.logout()
            # try again after we cleared the last saved values
            user_info = auth.authenticate()

            if user_info:
                print(f"Authenticated as: {user_info.get('email')}")
                print(f"Name: {user_info.get('name')}")

                # Verify with Next.js backend
                next_auth = auth.verify_with_nextjs()
                if next_auth:
                    print("Verified with Next.js backend")
                    print(f"User role: {next_auth.get('user', {}).get('role', 'unknown')}")
                    print(f"Next.js token: {next_auth.get('token')}")
                    return True, next_auth.get("token")
                else:
                    print("Failed to verify with Next.js backend")
                    return False, None
            else:
                print("Failed to verify with Next.js backend")
                return False, None

    return False, None


if __name__ == "__main__":
    main()
