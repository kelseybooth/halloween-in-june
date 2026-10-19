# Phase 2c.5 — The uses that change the world

Small, and deliberately separate. 2c builds the commands; this builds the three things that would otherwise have made 2c bigger than it should be. Nothing in 2c depends on it, so it can slip without stalling the developer.

## What is in it

**Lumber and the staircase.** Each `/use lumber` by a distinct player counts one plank against `planks_required`, read from `server_config`. The reply carries `{n}` and `{total}`. When the count of distinct players reaches the target, set `stairs_repaired` **server-wide**: the Entryway and Upstairs Hallway descriptions swap to their `stairs_repaired` rows and the staircase exits open for everyone. Lumber carries `present_when = !stairs_repaired`, so it disappears once the job is done — note the `!`, which the loader already supports.

This is also the game's only public `/use`. It posts in the room as well as privately, because the staircase is collective work and the others need to see it happen. 2c leaves `/use` private in every case; this phase adds the one exception, which means touching the reply routing 2c wrote.

**Graphite and the drawer.** `/use graphite` in the Upstairs Hallway sets `drawer_unjammed` for **that player only**, permanently. The roll-top desk's text switches to its `drawer_unjammed` row and the expired cat food source, gated on the same state, becomes visible to them. Used anywhere else, graphite prints its ordinary `use` text and changes nothing.

**Per-player take limits.** `max_per_player`, checked in `/take` before anything else happens. Three things set it, all at 1: the gourmet can, the skeleton key and the carving tools. Over the cap, the thing's own `take_fail` fires — all three have one written, and they read as refusals rather than errors ("You've already found yours").

The first two are the model for every state change in the game: the content files carry the text per state and the visibility gate, and the rule that sets the state lives in the Functional Spec. **Do not add a `sets_state` column.**

## What the split costs

**`/take` ships without caps.** This is the real price, and it is worth knowing rather than discovering. Between 2c and 2c.5 a player can take as many gourmet cans and carving tool sets as they like, and the "There's only one" refusals never fire. Harmless while the only players are testers. If 2c reaches a real server before this phase lands, the rare things are not rare, and the only fix afterwards is an admin taking them back by hand.

**The staircase is unfinishable in the meantime.** `/use lumber` will count — 2c builds the cooldown and the `thing_uses` row — but nothing happens when the count reaches the target, and the Upstairs Hallway stays shut. A tester who works out the mechanic and gets a group to the target will report that as a bug. Say so in advance.

**Nothing in 2d waits on this,** with one possible exception: the Story Bible floats a group achievement for the staircase, still unnamed and unresolved. If it turns out to exist, it reads `stairs_repaired` and so needs this phase first.

## Prerequisites

2c complete: `/use` with its four branches, `/take`, and the `thing_uses` row the lumber cooldown reads. `server_config` and `planks_required` have existed since 2b. Nothing else.

## Definition of done

- The `planks_required`-th distinct player opens the staircase for everyone, and both room descriptions swap
- Lumber disappears once `stairs_repaired` is set
- Placing a plank posts publicly as well as privately, and is the only `/use` that does
- Lowering `planks_required` below the planks already placed completes the staircase immediately rather than leaving it stuck
- `/use graphite` in the Upstairs Hallway reveals the drawer's source to that player and to nobody else
- `max_per_player` refuses with the thing's own `take_fail` on all three capped things

## What it does not do

**Secret Library discovery stays in 2e.** The tree, the skeleton key and the two per-player exit flags are a different mechanism — per-player exit visibility, reusing 2a's `rooms_unlocked` plumbing — and nothing else in Release 1 depends on them. Note that the skeleton key's cap lands here while the key itself stays unreachable until 2e, which is harmless: the cap simply has nothing to refuse yet.
