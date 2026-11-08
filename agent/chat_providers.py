"""Provider capability registry for the versioned PC chat protocol.

No real CLI backend is enabled here. A provider must be explicitly constructed
and injected by a caller after its runtime security contract is verified.
"""
from __future__ import annotations

import base64
import hashlib
import json


class ProviderUnavailable(ValueError):
    pass


class ProviderRegistry:
    def __init__(self, providers=()):
        self._providers = {}
        for provider in providers:
            name = getattr(provider, "name", None)
            if name not in ("claude", "codex", "fake") or name in self._providers:
                raise ValueError("provider-name")
            models = getattr(provider, "models", (None,))
            if not isinstance(models, (list, tuple)) or not models:
                raise ValueError("provider-models")
            if any(model is not None and (not isinstance(model, str) or not model or len(model) > 100) for model in models):
                raise ValueError("provider-models")
            self._providers[name] = (provider, tuple(models))

    @classmethod
    def from_providers(cls, providers):
        return cls(providers)

    def capabilities(self):
        return [{"provider": name, "models": list(models)} for name, (_provider, models) in self._providers.items()]

    def validate_turn(self, provider, model, binding_version):
        if binding_version != 2 or not isinstance(provider, str) or provider not in self._providers:
            raise ProviderUnavailable("binding-unavailable")
        instance, models = self._providers[provider]
        if model not in models:
            raise ProviderUnavailable("binding-unavailable")
        return instance


class CliSessionRefStore:
    """Persist opaque local CLI refs in the OS credential store, bound to device/session/provider/model."""

    def __init__(self, keystore, device_id):
        if not isinstance(device_id, str) or not device_id or len(device_id) > 128:
            raise ValueError("device-id")
        self.keystore, self.device_id = keystore, device_id

    @staticmethod
    def _account(handle):
        if not isinstance(handle, str) or not handle or len(handle) > 256:
            return None
        return "chat-session-ref:" + hashlib.sha256(handle.encode("utf-8")).hexdigest()

    def _binding_account(self, session_id):
        if not isinstance(session_id, str) or not session_id or len(session_id) > 128:
            return None
        digest = hashlib.sha256((self.device_id + "\0" + session_id).encode("utf-8")).hexdigest()
        return "chat-session-binding:" + digest

    def bind_session(self, session_id, provider, model):
        """Persist first selection; reject a later different binding, including after process restart."""
        account = self._binding_account(session_id)
        if not account or not isinstance(provider, str) or len(provider) > 32:
            return False
        if model is not None and (not isinstance(model, str) or len(model) > 100):
            return False
        expected = (self.device_id, session_id, provider, model)
        try:
            encoded = self.keystore.get(account)
            if encoded:
                raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
                return tuple(json.loads(raw)) == expected
            payload = base64.urlsafe_b64encode(json.dumps(expected, separators=(",", ":")).encode()).decode("ascii").rstrip("=")
            if len(payload) > 512:
                return False
            self.keystore.set(account, payload)
            return True
        except Exception:
            return False

    def put(self, handle, session_id, provider, model, cli_ref):
        account = self._account(handle)
        if not account or not all(isinstance(v, str) and 0 < len(v) <= 512 for v in (session_id, provider, cli_ref)):
            return False
        if model is not None and (not isinstance(model, str) or len(model) > 100):
            return False
        raw = json.dumps([self.device_id, session_id, provider, model, cli_ref], separators=(",", ":")).encode()
        encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
        if len(encoded) > 512:
            return False
        try:
            self.keystore.set(account, encoded)
            return True
        except Exception:
            return False

    def get(self, handle, session_id, provider, model):
        account = self._account(handle)
        if not account:
            return None
        try:
            encoded = self.keystore.get(account)
            if not isinstance(encoded, str):
                return None
            raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            device, saved_session, saved_provider, saved_model, cli_ref = json.loads(raw)
        except Exception:
            return None
        if (device, saved_session, saved_provider, saved_model) != (self.device_id, session_id, provider, model):
            return None
        return cli_ref if isinstance(cli_ref, str) and cli_ref else None
