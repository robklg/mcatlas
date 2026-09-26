"""Pure domain logic: decoders, analyzers and models.

Nothing in this package touches the filesystem, the network or a database. World data arrives
as bytes through the `WorldFiles` protocol; the import-linter contracts enforce this.
"""
