"""The search model, EmbeddingGemma 2: text and images become vectors that can be compared."""
import functools, threading

import numpy as np

from .config import MODEL

_model = None
VISION_TOKENS = 280  # model default; 70 is ~4x faster at some quality cost (70-1120 supported)

def model():
    global _model
    if _model is None:
        import torch
        from sentence_transformers import SentenceTransformer
        dev = "mps" if torch.backends.mps.is_available() else "cpu"
        # bf16 is safe for this model; float16 is not (per model card). Audio encoder not needed.
        _model = SentenceTransformer(MODEL, device=dev, config_kwargs={"audio_config": None},
                                     model_kwargs={"torch_dtype": torch.bfloat16 if dev == "mps" else torch.float32})
        proc = _model[0].processor
        proc.image_seq_length = proc.image_processor.image_seq_length = VISION_TOKENS
        proc.image_processor.max_soft_tokens = VISION_TOKENS
    return _model


_model_lock = threading.Lock()  # the web server answers in parallel; torch on MPS crashes the process if two threads encode at once

@functools.lru_cache(maxsize=512)
def embed_query(text):
    with _model_lock:
        return model().encode([text], prompt_name="SearchQuery", normalize_embeddings=True)[0].astype(np.float32)
