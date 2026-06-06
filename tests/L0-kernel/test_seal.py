"""Seal tests -- determinism, sensitivity to inputs/recipe/version."""

from husks.kernel import compute_seal, recipe_digest, NIL, CSE_VERSION


class TestRecipeDigest:
    def test_deterministic(self):
        r = [b"oracle", NIL, b"prompt", [b"tool1"], b"5"]
        assert recipe_digest(r) == recipe_digest(r)
        assert len(recipe_digest(r)) == 64

    def test_different_recipes(self):
        r1 = [b"oracle", NIL, b"prompt A", [], b"5"]
        r2 = [b"oracle", NIL, b"prompt B", [], b"5"]
        assert recipe_digest(r1) != recipe_digest(r2)


class TestComputeSeal:
    def test_deterministic(self):
        recipe = [b"action"]
        bindings = [(b"a.txt", b"abc123"), (b"b.txt", b"def456")]
        assert compute_seal(CSE_VERSION, recipe, bindings) == compute_seal(CSE_VERSION, recipe, bindings)

    def test_different_inputs_different_seal(self):
        recipe = [b"action"]
        b1 = [(b"a.txt", b"abc123")]
        b2 = [(b"a.txt", b"xyz789")]
        assert compute_seal(CSE_VERSION, recipe, b1) != compute_seal(CSE_VERSION, recipe, b2)

    def test_different_recipe_different_seal(self):
        r1 = [b"action"]
        r2 = [b"oracle", NIL, b"do stuff", [], b"5"]
        bindings = [(b"a.txt", b"abc123")]
        assert compute_seal(CSE_VERSION, r1, bindings) != compute_seal(CSE_VERSION, r2, bindings)

    def test_different_version_different_seal(self):
        recipe = [b"action"]
        bindings = [(b"a.txt", b"abc123")]
        s1 = compute_seal(b"1", recipe, bindings)
        s2 = compute_seal(b"2", recipe, bindings)
        assert s1 != s2

    def test_seal_is_hex_64(self):
        seal = compute_seal(CSE_VERSION, [b"action"], [])
        assert len(seal) == 64
        int(seal, 16)  # must be valid hex

    def test_empty_bindings(self):
        s1 = compute_seal(CSE_VERSION, [b"action"], [])
        s2 = compute_seal(CSE_VERSION, [b"action"], [(b"x", b"y")])
        assert s1 != s2

    def test_binding_order_matters(self):
        recipe = [b"action"]
        b1 = [(b"a", b"1"), (b"b", b"2")]
        b2 = [(b"b", b"2"), (b"a", b"1")]
        assert compute_seal(CSE_VERSION, recipe, b1) != compute_seal(CSE_VERSION, recipe, b2)
