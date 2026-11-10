"""Herd — keep one Hermes across every machine.

The store only ever holds ciphertext. Every device owns exactly one metadata
file, so two machines pushing at the same time can never clobber each other.
"""

__version__ = "1.2.0"
