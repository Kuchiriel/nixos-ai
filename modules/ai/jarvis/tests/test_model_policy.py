

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
