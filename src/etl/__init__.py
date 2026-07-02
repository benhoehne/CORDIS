"""
ETL package – repeatable delta-update workflows (Task 2).

update_cordis : refresh cordis_projects from a new CORDIS export.
update_erc    : refresh erc_projects from a new ERC-dashboard dump.
"""

from .update_cordis import update_cordis
from .update_erc import update_erc

__all__ = ["update_cordis", "update_erc"]
