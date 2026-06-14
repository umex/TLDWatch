"""Settings service: load, save, and PATCH the on-disk settings file.

The settings file is the serialisation of :class:`Settings` (D-14).
The model is the source of truth; the file is a snapshot.

In-memory state is held in a tiny module-level :class:`_State`. The
lifespan in :mod:`app.main` calls :func:`load_settings_from_disk` to
read the bootstrap file, then :func:`configure` to install the
result. Route handlers read the in-memory value via :func:`current`,
and :func:`apply_update` performs a PATCH that persists to disk and
updates the in-memory state only AFTER the disk write succeeds
(Codex HIGH item 16).
"""
