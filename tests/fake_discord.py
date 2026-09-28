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

        self.id = abs(hash(("channel", name))) % (10**9)
        # Everything posted here, in order. The achievement announcements are
        # read straight off this.
        self.posted: list[str] = []
        self.send_fails = False

        self.created: list[str] = []
        self.create_fails: set[str] = set()
        self.delete_fails: set[str] = set()
        self.edit_fails: set[str] = set()
        self.add_user_fails: set[str] = set()
        self.archived_forbidden = False

    async def send(self, content=None, **kwargs):
        if self.send_fails:
            raise http_error(message="channel send failed")
        self.posted.append(content)
        return SimpleNamespace(id=len(self.posted))

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


class FakeMember:
    """Somebody to DM an unlock description to.

    `dms_open` is the case worth modelling rather than the happy one: people
    close their DMs, and an achievement that raises because of it would cost
    the player the award it was announcing.
    """

    def __init__(self, user_id, *, dms_open=True):
        self.id = user_id
        self.mention = f"<@{user_id}>"
        self.dms_open = dms_open
        self.dms: list[str] = []

    async def send(self, content=None, **kwargs):
        if not self.dms_open:
            raise http_error(discord.Forbidden, 403, "Cannot send messages to this user")
        self.dms.append(content)


class FakeGuild:
    """A guild that can find its own channels and members by id."""

    def __init__(self, guild_id, *, name="Test Server", channels=(), members=()):
        self.id = guild_id
        self.name = name
        self.text_channels = list(channels)
        self.me = SimpleNamespace()
        self._members = {m.id: m for m in members}
        for channel in self.text_channels:
            channel.guild = self

    def get_channel(self, channel_id):
        return next((c for c in self.text_channels if c.id == channel_id), None)

    def get_member(self, user_id):
        return self._members.get(user_id)

    def add_member(self, member):
        self._members[member.id] = member
        return member


class FakeResponse:
    def __init__(self, interaction):
        self._interaction = interaction

    def is_done(self):
        return self._interaction.deferred

    async def defer(self, **kwargs):
        self._interaction.deferred = True
        self._interaction.defer_kwargs = kwargs

    async def send_message(self, content=None, **kwargs):
        self._interaction.sent.append((content, kwargs))


class FakeFollowup:
    def __init__(self, interaction):
        self._interaction = interaction

    async def send(self, content=None, **kwargs):
        self._interaction.sent.append((content, kwargs))
        return SimpleNamespace(id=1)


class FakeInteraction:
    """Just enough of discord.Interaction for a command handler to run.

    Records what was sent and whether it was ephemeral, which between them are
    most of what a command's behaviour actually is.
    """

    def __init__(self, user_id, guild_id, *, guild=None):
        self.user = SimpleNamespace(
            id=user_id, mention=f"<@{user_id}>", display_name=f"Player {user_id}"
        )
        self.guild_id = guild_id
        self.guild = guild
        self.deferred = False
        self.defer_kwargs = {}
        self.sent: list[tuple[str | None, dict]] = []
        self.response = FakeResponse(self)
        self.followup = FakeFollowup(self)

    @property
    def reply(self) -> str:
        """The text of the last thing sent."""
        assert self.sent, "nothing was sent"
        return self.sent[-1][0] or ""

    @property
    def embed(self):
        """The embed of the last thing sent, or None if it was plain text."""
        assert self.sent, "nothing was sent"
        return self.sent[-1][1].get("embed")

    @property
    def was_private(self) -> bool:
        assert self.sent, "nothing was sent"
        return bool(self.sent[-1][1].get("ephemeral"))
