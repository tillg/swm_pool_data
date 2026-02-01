"""Tests for transform module."""

import pytest
from transform import resolve_facility_alias


class TestResolveFacilityAlias:
    """Tests for resolve_facility_alias function."""

    def test_alias_match(self):
        """Should return canonical name when alias exists."""
        aliases = {
            "sauna:Dantebad Sauna": "Dantebad",
            "sauna:Nordbad Sauna": "Nordbad",
        }
        result = resolve_facility_alias("Dantebad Sauna", "sauna", aliases)
        assert result == "Dantebad"

    def test_no_match_passthrough(self):
        """Should return original name when no alias exists."""
        aliases = {
            "sauna:Dantebad Sauna": "Dantebad",
        }
        result = resolve_facility_alias("Müller'sches Volksbad", "sauna", aliases)
        assert result == "Müller'sches Volksbad"

    def test_type_aware_lookup(self):
        """Should only match when facility type matches."""
        aliases = {
            "sauna:Nordbad Sauna": "Nordbad",
        }
        # Pool should not match sauna alias
        result = resolve_facility_alias("Nordbad Sauna", "pool", aliases)
        assert result == "Nordbad Sauna"

    def test_empty_aliases(self):
        """Should return original name with empty aliases dict."""
        result = resolve_facility_alias("Dantebad Sauna", "sauna", {})
        assert result == "Dantebad Sauna"
