from passlib.context import CryptContext
from typing import Optional

class Hashing:
    def __init__(self, hash_rounds: int = 12):
        """
        Initialize the Hashing class with a specific number of hash rounds.
        :param hash_rounds: The number of rounds for bcrypt hashing (default is 12).
        """        
        self.hash_rounds = hash_rounds
        self.crypt_context = CryptContext(schemes=["bcrypt"], default="bcrypt", bcrypt__rounds=self.hash_rounds)

    def verify_password(self, input_password: str, hashed_password: str) -> bool:
        """
        Verify if the provided password matches the hashed password.
        :param input_password: The password to verify.
        :param hashed_password: The hashed password.
        :return: True if the password matches, False otherwise.
        """
        if not input_password or not hashed_password:
            raise ValueError("Input password or hashed password cannot be empty.")
        
        return self.crypt_context.verify(input_password, hashed_password)

    def get_password_hash(self, input_password: str) -> str:
        """
        Hash the provided password.
        :param input_password: The password to hash.
        :return: The hashed password.
        """
        if not input_password:
            raise ValueError("Input password cannot be empty.")        
        return self.crypt_context.hash(input_password)

