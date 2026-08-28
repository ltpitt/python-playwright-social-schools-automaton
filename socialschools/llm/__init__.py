"""LLM backends, all of them pure text transformers (ADR 0002).

Article and Attachment text is untrusted input, so no provider here may ever
send tools, functions or fetchable URLs. The worst case of a poisoned message
must stay "a low-quality Digest", never code execution or a network side effect
chosen by the model.

Providers are built lazily by `provider.get_provider()`, which is only reached
from the Digest path. Translation mode loads none of this.
"""
