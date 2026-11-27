"""Email and password accounts: sign up, log in, and the access token a user then sends.

A user acts as the owner id `user:<id>`, so every owner-scoped route (profiles, saved jobs,
the match feed) works for them exactly as for API-key and identity-provider callers.
"""

from sanket.accounts.identity import owner_id_for, user_id_of

__all__ = ["owner_id_for", "user_id_of"]
