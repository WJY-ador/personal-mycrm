import unittest

from agent import chat, chat_providers


class ProviderRegistryTest(unittest.TestCase):
    def test_empty_registry_advertises_no_provider(self):
        registry = chat_providers.ProviderRegistry()
        self.assertEqual(registry.capabilities(), [])
        with self.assertRaises(chat_providers.ProviderUnavailable):
            registry.validate_turn("claude", None, 2)


class RefStoreTest(unittest.TestCase):
    class Store:
        def __init__(self): self.values = {}
        def set(self, key, value): self.values[key] = value
        def get(self, key): return self.values.get(key)

    def test_persists_opaque_ref_and_checks_device_session_provider_model(self):
        backend = self.Store()
        one = chat_providers.CliSessionRefStore(backend, "device-A")
        self.assertTrue(one.bind_session("session-A", "claude", "sonnet"))
        restarted = chat_providers.CliSessionRefStore(backend, "device-A")
        self.assertTrue(restarted.bind_session("session-A", "claude", "sonnet"))
        self.assertFalse(restarted.bind_session("session-A", "codex", "sonnet"))
        self.assertTrue(one.put("opaque-handle", "session-A", "claude", "sonnet", "cli-raw-ref"))
        self.assertNotIn("cli-raw-ref", repr(backend.values))
        self.assertEqual(restarted.get("opaque-handle", "session-A", "claude", "sonnet"), "cli-raw-ref")
        self.assertIsNone(chat_providers.CliSessionRefStore(backend, "device-B").get("opaque-handle", "session-A", "claude", "sonnet"))
        self.assertIsNone(restarted.get("opaque-handle", "session-B", "claude", "sonnet"))
        self.assertIsNone(restarted.get("opaque-handle", "session-A", "codex", "sonnet"))
        self.assertIsNone(restarted.get("opaque-handle", "session-A", "claude", "opus"))

    def test_explicit_fake_capability_requires_exact_v2_binding(self):
        fake = chat.FakeProvider(step=0)
        registry = chat_providers.ProviderRegistry.from_providers([fake])
        self.assertEqual(registry.capabilities(), [{"provider": "fake", "models": [None]}])
        self.assertIs(registry.validate_turn("fake", None, 2), fake)
        for args in (("claude", None, 2), ("fake", "unknown", 2), ("fake", None, 1), ("fake", None, None)):
            with self.subTest(args=args), self.assertRaises(chat_providers.ProviderUnavailable):
                registry.validate_turn(*args)

    def test_model_capability_is_explicit_and_exact(self):
        class ModelProvider:
            name = "claude"
            models = ("claude-sonnet-4-5",)

        provider = ModelProvider()
        registry = chat_providers.ProviderRegistry.from_providers([provider])
        self.assertIs(registry.validate_turn("claude", "claude-sonnet-4-5", 2), provider)
        with self.assertRaises(chat_providers.ProviderUnavailable):
            registry.validate_turn("claude", None, 2)


if __name__ == "__main__":
    unittest.main()
