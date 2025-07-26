"""
Authentication Service - Handles user authentication and authorization.
Separated from EMV reading logic for better modularity.
"""

import json
from typing import Dict, Optional


class User:
    """User data model"""
    
    def __init__(self, pan: str, name: str, access_level: str = "user", active: bool = True):
        self.pan = pan
        self.name = name
        self.access_level = access_level
        self.active = active

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "access_level": self.access_level,
            "active": self.active
        }

    @classmethod
    def from_dict(cls, pan: str, data: Dict) -> "User":
        return cls(
            pan=pan,
            name=data["name"],
            access_level=data.get("access_level", "user"),
            active=data.get("active", True)
        )


class AuthenticationService:
    """Service for user authentication and management"""

    def __init__(self, db_file: str = "users.json"):
        self.db_file = db_file
        self.users = self._load_users()

    def authenticate_user(self, pan: str) -> Optional[User]:
        """
        Authenticate a user by their PAN
        Returns User object if authentication successful, None otherwise
        """
        if pan in self.users and self.users[pan].active:
            return self.users[pan]
        return None

    def add_user(self, pan: str, name: str, access_level: str = "user") -> bool:
        """
        Add a new user to the system
        Returns True if successful, False if user already exists
        """
        if pan in self.users:
            return False
        
        user = User(pan, name, access_level)
        self.users[pan] = user
        self._save_users()
        return True

    def remove_user(self, pan: str) -> bool:
        """
        Remove a user from the system
        Returns True if successful, False if user doesn't exist
        """
        if pan not in self.users:
            return False
        
        del self.users[pan]
        self._save_users()
        return True

    def deactivate_user(self, pan: str) -> bool:
        """
        Deactivate a user (keep in database but deny access)
        Returns True if successful, False if user doesn't exist
        """
        if pan not in self.users:
            return False
        
        self.users[pan].active = False
        self._save_users()
        return True

    def activate_user(self, pan: str) -> bool:
        """
        Activate a user
        Returns True if successful, False if user doesn't exist
        """
        if pan not in self.users:
            return False
        
        self.users[pan].active = True
        self._save_users()
        return True

    def list_users(self) -> Dict[str, User]:
        """List all users in the system"""
        return self.users.copy()

    def get_user_count(self) -> int:
        """Get total number of users"""
        return len(self.users)

    def get_active_user_count(self) -> int:
        """Get number of active users"""
        return sum(1 for user in self.users.values() if user.active)

    def _load_users(self) -> Dict[str, User]:
        """Load users from JSON file"""
        try:
            with open(self.db_file, "r") as f:
                data = json.load(f)
                return {pan: User.from_dict(pan, user_data) for pan, user_data in data.items()}
        except FileNotFoundError:
            # Create default users if file doesn't exist
            default_users = {
                "4111111111111111": User("4111111111111111", "John Doe", "admin"),
                "5555555555554444": User("5555555555554444", "Jane Smith", "user"),
            }
            self._save_users_dict(default_users)
            return default_users

    def _save_users(self):
        """Save current users to JSON file"""
        self._save_users_dict(self.users)

    def _save_users_dict(self, users: Dict[str, User]):
        """Save users dictionary to JSON file"""
        data = {pan: user.to_dict() for pan, user in users.items()}
        with open(self.db_file, "w") as f:
            json.dump(data, f, indent=2)
