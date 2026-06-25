import os
import google.auth
from google.auth.credentials import Credentials
from unittest.mock import MagicMock

class DummyCredentials(Credentials):
    def __init__(self):
        super().__init__()
        self.token = "dummy-token"

    def refresh(self, request):
        self.token = "dummy-token"

# Mock google.auth.default to return dummy credentials and project
google.auth.default = lambda *args, **kwargs: (DummyCredentials(), "dummy-project")

# Set dummy environment variables
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "dummy-project")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "False")

# Mock google.cloud.logging Client
import google.cloud.logging
google.cloud.logging.Client = MagicMock()

# Mock google.genai Client for offline testing
import google.genai
from google.genai import types

class MockModelsService:
    def __init__(self, is_async=False):
        self._is_async = is_async

    def generate_content(self, model, contents, config=None, **kwargs):
        response = types.GenerateContentResponse(
            candidates=[
                types.Candidate(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part.from_text(text="This is a mock non-streaming response.")
                        ]
                    )
                )
            ]
        )
        if self._is_async:
            async def _async_val():
                return response
            return _async_val()
        return response

    async def generate_content_stream(self, model, contents, config=None, **kwargs):
        async def _gen():
            yield types.GenerateContentResponse(
                candidates=[
                    types.Candidate(
                        content=types.Content(
                            role="model",
                            parts=[
                                types.Part.from_text(text="This is a mock streaming response chunk.")
                            ]
                        )
                    )
                ]
            )
        return _gen()

class MockLiveService:
    def connect(self, *args, **kwargs):
        class AsyncContextManager:
            async def __aenter__(self):
                return MagicMock()
            async def __exit__(self, exc_type, exc_val, exc_tb):
                pass
        return AsyncContextManager()

class MockAio:
    def __init__(self, client):
        self.models = MockModelsService(is_async=True)
        self.live = MockLiveService()

class MockClient:
    def __init__(self, **kwargs):
        self.vertexai = kwargs.get("vertexai", False)
        self.models = MockModelsService(is_async=False)
        self.aio = MockAio(self)

# Patch the Client class in google.genai
google.genai.Client = MockClient

