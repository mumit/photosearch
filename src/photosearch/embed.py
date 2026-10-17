"""The search model, EmbeddingGemma 2: text and images become vectors that can be compared."""
import functools, threading

import numpy as np

from .config import MODEL

_model, _audio = None, False
VISION_TOKENS = 280  # model default; 70 is ~4x faster at some quality cost (70-1120 supported)

def model(audio=False):
    """The model; with audio, the one that can also hear (300M more, so only `photosearch videos` loads it). Both
    give the same vectors for text and images."""
    global _model, _audio
    if _model is None or (audio and not _audio):
        import torch
        from sentence_transformers import SentenceTransformer
        dev = "mps" if torch.backends.mps.is_available() else "cpu"
        # bf16 is safe for this model; float16 is not (per model card)
        _model = SentenceTransformer(MODEL, device=dev, config_kwargs={} if audio else {"audio_config": None},
                                     model_kwargs={"torch_dtype": torch.bfloat16 if dev == "mps" else torch.float32})
        set_vision_tokens(_model, VISION_TOKENS); _audio = audio
    return _model


def set_vision_tokens(m, n):
    """How many tokens each image becomes from now on (the index records it; `photosearch eval` compares others)."""
    proc = m[0].processor
    proc.image_seq_length = proc.image_processor.image_seq_length = n
    proc.image_processor.max_soft_tokens = n


_model_lock = threading.Lock()  # the web server answers in parallel; torch on MPS crashes the process if two threads encode at once

@functools.lru_cache(maxsize=512)
def embed_query(text):
    with _model_lock:
        return model().encode([text], prompt_name="SearchQuery", normalize_embeddings=True)[0].astype(np.float32)
