import asyncio
import hashlib

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

pwd_hasher = PasswordHasher(time_cost=3, memory_cost=64*1024, parallelism=1) # Default settings, need to be tweaked in the future

async def hash_password(pwd: str) -> str:
    return await asyncio.get_running_loop().run_in_executor(None, pwd_hasher.hash, pwd)

async def verify_password(hash: str, pwd: str) -> bool:
    """
    Verifies consistency between hash and pwd.
    Runs in a thread to prevent CPU time wasting.
    """

    try:
        return await asyncio.get_running_loop().run_in_executor(None, pwd_hasher.verify, hash, pwd)
    except VerifyMismatchError:
        return False

def hash_token(token: str) -> str:
    """
    Hashes a token into an hex string using sha256
    """

    return hashlib.sha256(token.encode()).hexdigest()
