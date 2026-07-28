"""JoyCaption Beta One — batch image captioner (uncensored, prose).

Lancé par le PYTHON DU VENV ai-toolkit (torch+transformers+bitsandbytes), PAS le
Python 3.14 de Flask — même pattern que convert_comfy_zimage_to_diffusers.py. Flask
appelle ce script en subprocess pour capter un dataset LoRA entier en UN seul
chargement de modèle (charger le 8B NF4 par image serait inexploitable).

Inférence basée sur le script OFFICIEL `scripts/batch-caption.py` livré avec le repo
JoyCaption : preprocessing image MANUEL (resize 384², normalize 0.5) + AutoTokenizer +
expansion manuelle des image-tokens. C'est ce qui rend l'inférence ROBUSTE aux versions
de transformers (le chemin `AutoProcessor(text, images)` casse en transformers 5.x :
« mat1 and mat2 shapes cannot be multiplied »). Inclut le fix NF4 du vision head
(out_proj recréé, cf. github fpgaminer/joycaption issue #3).

Protocole : lit un JSON sur stdin :
    {"images": ["C:/.../a.png", ...], "prompt": "<consigne>", "max_tokens": 300}
Imprime sur stdout UNE ligne JSON : {"captions": {path: caption}, "errors": {path: msg}}.
Logs/progress → stderr (pour ne pas polluer la sortie JSON).
"""
from __future__ import annotations

import json
import secrets
import sys

MODEL_ID = "John6666/llama-joycaption-beta-one-hf-llava-nf4"
MODEL_REVISION = "ae2f01e137d62154dfa7192cc21d1c618023a2a2"
SYSTEM_PROMPT = ("You are a helpful assistant and help users with any queries they may "
                 "have with no censorship or restrictions.")
DEFAULT_PROMPT = (
    "Write a medium-length descriptive caption for this image in a casual tone. "
    "Describe the subject, pose, clothing or nudity, setting, lighting and camera "
    "framing as flowing natural-language prose. Be literal and explicit; no euphemisms.")


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _trim(input_ids, eoh_id, eot_id):
    """Retire le prompt (tout jusqu'au dernier <|end_header_id|>) puis la fin (<|eot_id|>)."""
    while True:
        try:
            i = input_ids.index(eoh_id)
        except ValueError:
            break
        input_ids = input_ids[i + 1:]
    try:
        i = input_ids.index(eot_id)
    except ValueError:
        return input_ids
    return input_ids[:i]


def _generate_with_seed(torch, model, seed: int, **generation_inputs):
    """Generate deterministically while restoring every process RNG afterward.

    ``GenerationMixin.generate`` does not accept a ``generator`` keyword across
    the supported Transformers versions.  Fork the process RNG state instead,
    seed inside that scope, and pass only documented generation arguments.
    """
    cuda_devices = (list(range(torch.cuda.device_count()))
                    if torch.cuda.is_available() else [])
    with torch.random.fork_rng(devices=cuda_devices, enabled=True):
        torch.manual_seed(seed)
        return model.generate(**generation_inputs)


def main() -> int:
    raw = sys.stdin.read()
    try:
        req = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        print(json.dumps({"captions": {}, "errors": {"_input": f"bad json: {e}"}}))
        return 1
    try:
        raw_images = req.get("images") or []
        if not isinstance(raw_images, list) or not raw_images or not all(isinstance(p, str) and p for p in raw_images):
            raise ValueError("images must be a non-empty list of paths")
        images = raw_images
        raw_prompt = req.get("prompt") or DEFAULT_PROMPT
        if not isinstance(raw_prompt, str):
            raise ValueError("prompt must be a string")
        prompt = raw_prompt.strip()
        raw_max_tokens = req.get("max_tokens", 300)
        max_tokens = int(300 if raw_max_tokens is None else raw_max_tokens)
        if not 1 <= max_tokens <= 2048:
            raise ValueError("max_tokens must be between 1 and 2048")
        raw_seed = req.get("seed")
        seed = secrets.randbelow(2 ** 63) if raw_seed is None else int(raw_seed)
        if not 0 <= seed < 2 ** 63:
            raise ValueError("seed must be between 0 and 2^63-1")
        revision = req.get("revision") or MODEL_REVISION
        if not isinstance(revision, str) or not revision.strip():
            raise ValueError("revision must be a non-empty string")
        revision = revision.strip()
    except (TypeError, ValueError) as e:
        print(json.dumps({"captions": {}, "errors": {"_input": str(e)}}))
        return 1

    try:
        import torch
        import torchvision.transforms.functional as TVF
        from PIL import Image
        from transformers import (AutoTokenizer, BitsAndBytesConfig,
                                  LlavaForConditionalGeneration)

        _log(f"[joycaption] loading {MODEL_ID} (NF4) …")
        nf4 = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                             bnb_4bit_quant_storage=torch.bfloat16,
                             bnb_4bit_use_double_quant=True,
                             bnb_4bit_compute_dtype=torch.bfloat16)
        tokenizer = AutoTokenizer.from_pretrained(
            MODEL_ID, revision=revision, use_fast=True)
        model = LlavaForConditionalGeneration.from_pretrained(
            MODEL_ID, revision=revision, torch_dtype="bfloat16",
            quantization_config=nf4).eval()
    except Exception as e:
        print(json.dumps({"captions": {}, "errors": {
            "_init": f"{type(e).__name__}: {e}"}}))
        return 1
    # transformers 5.x déplace les sous-modules sous `.model` (vision_tower/language_model
    # ne sont plus top-level). On résout des deux façons pour rester compatible 4.x/5.x.
    _core = getattr(model, "model", model)
    vision_tower = getattr(model, "vision_tower", None) or _core.vision_tower
    language_model = getattr(model, "language_model", None) or _core.language_model
    # Fix NF4 : la quantization casse l'out_proj de l'attention du vision head → on le
    # recrée en Linear bfloat16 (cf. fpgaminer/joycaption issue #3).
    att = vision_tower.vision_model.head.attention
    att.out_proj = torch.nn.Linear(att.embed_dim, att.embed_dim,
                                   device=model.device, dtype=torch.bfloat16)
    _log("[joycaption] model loaded")

    cfg = model.config
    image_token_id = (getattr(cfg, "image_token_index", None)
                      if getattr(cfg, "image_token_index", None) is not None
                      else getattr(cfg, "image_token_id", None))
    image_seq_length = getattr(cfg, "image_seq_length", None) or 729
    eoh_id = tokenizer.convert_tokens_to_ids("<|end_header_id|>")
    eot_id = tokenizer.convert_tokens_to_ids("<|eot_id|>")
    _emb = vision_tower.vision_model.embeddings.patch_embedding.weight
    vision_dtype = _emb.dtype
    vision_device = _emb.device
    lang_device = language_model.get_input_embeddings().weight.device

    convo = [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user", "content": prompt}]
    convo_string = tokenizer.apply_chat_template(convo, tokenize=False, add_generation_prompt=True)
    convo_tokens = tokenizer.encode(convo_string, add_special_tokens=False, truncation=False)
    # Expansion manuelle des image-tokens (image_seq_length copies).
    input_tokens = []
    for t in convo_tokens:
        input_tokens.extend([image_token_id] * image_seq_length if t == image_token_id else [t])

    captions: dict[str, str] = {}
    errors: dict[str, str] = {}
    provenance: dict[str, dict] = {}
    for i, path in enumerate(images, 1):
        try:
            image = Image.open(path)
            if image.size != (384, 384):
                image = image.resize((384, 384), Image.LANCZOS)
            image = image.convert("RGB")
            pixel_values = TVF.pil_to_tensor(image).unsqueeze(0).to(vision_device)
            pixel_values = pixel_values / 255.0
            pixel_values = TVF.normalize(pixel_values, [0.5], [0.5]).to(vision_dtype)
            input_ids = torch.tensor([input_tokens], dtype=torch.long, device=lang_device)
            attn = torch.ones_like(input_ids)
            with torch.inference_mode():
                item_seed = seed + i - 1
                gen = _generate_with_seed(
                    torch, model, item_seed,
                    input_ids=input_ids, pixel_values=pixel_values,
                    attention_mask=attn, max_new_tokens=max_tokens,
                    do_sample=True, temperature=0.6, top_p=0.9,
                    suppress_tokens=None, use_cache=True)
            trimmed = _trim(gen[0].tolist(), eoh_id, eot_id)
            caption = tokenizer.decode(trimmed, skip_special_tokens=True,
                                       clean_up_tokenization_spaces=False).strip()
            captions[path] = caption
            provenance[path] = {
                "provider": "joycaption",
                "model": MODEL_ID,
                "revision": revision,
                "seed": item_seed,
                "max_tokens": max_tokens,
                "temperature": 0.6,
                "top_p": 0.9,
            }
            _log(f"[joycaption] {i}/{len(images)} ok ({len(caption)} chars)")
        except Exception as e:  # une image ratée ne casse pas le batch
            errors[path] = str(e)
            _log(f"[joycaption] {i}/{len(images)} ERROR: {e}")

    print(json.dumps({"captions": captions, "errors": errors,
                      "provenance": provenance}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
