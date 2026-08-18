import secrets

import bcrypt


class Security:
    """Password hashing and token generation."""

    @staticmethod
    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(password.encode()[:72], password_hash.encode())
        except ValueError:
            return False

    @staticmethod
    def new_token() -> str:
        return secrets.token_hex(32)
