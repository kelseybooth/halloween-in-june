"""Just enough of discord.py to exercise the thread operations offline.

Only the surface `house_utils` actually touches is modelled: threads have a
name, an archived and a locked flag, and can be deleted, edited and added to;
channels list their threads, page their archived ones, and create new ones.
Failures are injected by name so the error paths can be driven deliberately.
"""

from types import SimpleNamespace

import discord


def http_error(cls=discord.HTTPException, status=500, message="boom"):
    """A real discord exception instance, which needs a response-shaped object."""
    return cls(SimpleNamespace(status=status, reason=message), message)


class FakeThread:
    def __init__(self, name, *, archived=False, locked=False, channel=None):
        self.id = abs(hash((name, archived, locked))) % (10**9)
        self.name = name
        self.archived = archived
        self.locked = locked
        self._channel = channel
        self.added_users: list[int] = []
        self.removed_users: list[int] = []
        self.deleted = False

    async def delete(self):
        if self.name in getattr(self._channel, "delete_fails", ()):
            raise http_error(message=f"cannot delete {self.name}")
        self.deleted = True
        if self._channel is not None and self in self._channel.threads:
            self._channel.threads.remove(self)

    async def edit(self, **kwargs):
        if self.name in getattr(self._channel, "edit_fails", ()):
            raise http_error(message=f"cannot edit {self.name}")
        for key, value in kwargs.items():
            setattr(self, key, value)

    async def add_user(self, user):
        if self.name in getattr(self._channel, "add_user_fails", ()):
            raise http_error(message=f"cannot add to {self.name}")
        self.added_users.append(user.id)

    async def remove_user(self, user):
        self.removed_users.append(user.id)


class FakeChannel:
    """A text channel holding threads.

    `archived` threads are kept apart from active ones, exactly as Discord does:
    they are absent from `channel.threads` and only reachable by paging
    `archived_threads()`, which is the distinction the thread code has to get
    right.
    """

    def __init__(self, *, name="halloween", guild_name="Test Server", archived=()):
        self.name = name
        self.guild = SimpleNamespace(name=guild_name, me=SimpleNamespace())
        self.threads: list[FakeThread] = []
        self.archived_list: list[FakeThread] = [
            t if isinstance(t, FakeThread) else FakeThread(t, archived=True, channel=self)
            for t in archived
        ]
        for thread in self.archived_list:
            thread._channel = self

        self.created: list[str] = []
        self.create_fails: set[str] = set()
        self.delete_fails: set[str] = set()
        self.edit_fails: set[str] = set()
        self.add_user_fails: set[str] = set()
        self.archived_forbidden = False

    def add_active(self, *names):
        for name in names:
            self.threads.append(FakeThread(name, channel=self))
        return self

    def archived_threads(self, *, private, limit=None):
        channel = self

        class _Pager:
            def __aiter__(self):
                async def gen():
                    if channel.archived_forbidden:
                        raise http_error(discord.Forbidden, 403, "Missing Access")
                    # Private threads are what the house uses; the public page
                    # is empty, as it would be in a real server.
                    if private:
                        for thread in list(channel.archived_list):
                            yield thread

                return gen()

        return _Pager().__aiter__()

    async def create_thread(self, *, name, type=None, auto_archive_duration=None, invitable=None):
        if name in self.create_fails:
            raise http_error(message=f"cannot create {name}")
        self.created.append(name)
        thread = FakeThread(name, channel=self)
        thread.type = type
        thread.auto_archive_duration = auto_archive_duration
        thread.invitable = invitable
        self.threads.append(thread)
        return thread

    def permissions_for(self, _member):
        return self._permissions

    def with_permissions(self, **flags):
        self._permissions = SimpleNamespace(**flags)
        return self
