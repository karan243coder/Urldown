# BIMBO v4.0 - Backward-compatible DB wrapper (points to new unified DB)
import datetime
from database.users_chats_db import db as _db


class Database:
    """Backward-compat shim — routes to new unified users_chats_db."""

    def __init__(self, uri, database_name):
        self.db = _db

    def new_user(self, id):
        return dict(id=id, thumbnail=None)

    async def add_user(self, id, name="", username=""):
        await self.db.add_user(int(id), name=name, username=username)

    async def is_user_exist(self, id):
        # We add user on first contact anyway, but keep API
        if self.db._use_fb:
            return int(id) in self.db._fallback["users"]
        return await self.db.users.find_one({"id": int(id)}) is not None

    async def total_users_count(self):
        return await self.db.total_users()

    async def get_all_users(self):
        return await self.db.get_all_users()

    async def delete_user(self, user_id):
        await self.db.delete_user(int(user_id))

    async def set_thumbnail(self, id, thumbnail):
        await self.db.set_thumb(int(id), thumbnail)

    async def get_thumbnail(self, id):
        return await self.db.get_thumb(int(id))

    async def del_thumbnail(self, id):
        return await self.db.del_thumb(int(id))
