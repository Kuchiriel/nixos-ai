

class TestFramingFor:
    def test_known_models(self):
        from jarvis.core.model_policy import ModelPolicy
        assert "thinking" in ModelPolicy.framing_for("nemotron-3-super")
        assert "JSON" in ModelPolicy.framing_for("ling-3-flash-fin")
        assert "concise" in ModelPolicy.framing_for("mimo-v2.5").lower()
        assert "plan" in ModelPolicy.framing_for("muse-spark-1.3").lower()

    def test_unknown_empty(self):
        from jarvis.core.model_policy import ModelPolicy
        assert ModelPolicy.framing_for("modelo-xyz-999") == ""
        assert ModelPolicy.framing_for("") == ""


class TestCascade:
    def test_layers_known(self):
        from jarvis.core import model_policy as mp
        for layer in ("coding-long", "dev", "batch", "mechanical",
                      "docs", "classify", "rag", "vision"):
            entries = mp.cascade_for(layer)
            assert entries, layer
            for provider, model, base, key in entries:
                assert provider and model and base.startswith("https://")
                assert key.endswith("_KEY") or key.endswith("CONFIG") or key.endswith("_TOKEN")

    def test_unknown_empty(self):
        from jarvis.core import model_policy as mp
        assert mp.cascade_for("inexistente-xyz") == []

    def test_key_present(self):
        import os
        from jarvis.core import model_policy as mp
        os.environ["TEST_CASCADE_KEY_X"] = "abc"
        assert mp.cascade_key_present(("p", "m", "https://x", "TEST_CASCADE_KEY_X"))
        del os.environ["TEST_CASCADE_KEY_X"]
        assert not mp.cascade_key_present(("p", "m", "https://x", "TEST_CASCADE_KEY_X"))
