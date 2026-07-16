"""Face similarity scorer — InsightFace antelopev2, lance dans un interprete DEDIE
(insightface y est installe, PAS dans le venv Flask). CPU (onnxruntime CPU-only ici)
-> pas de GPU, ne touche pas ComfyUI.
Protocole stdin: {"ref": path, "refs": [paths], "images": [paths],
"models_root": path|null} -> stdout UNE ligne JSON
{"ref_ok": bool, "refs_used": int, "results": {path: {state, sim?, det,
bbox_frac, yaw, face_count, face_sharpness, face_exposure}}}.
Logs -> stderr.
Gating 3-etats + padding rescue (valide empiriquement sur test3)."""
from __future__ import annotations
import json, sys

DET_MIN, BBOX_MIN, YAW_MAX = 0.50, 0.06, 40.0


def _log(m): print(m, file=sys.stderr, flush=True)


def _repair_nested_antelopev2(models_root=None):
    """L'antelopev2.zip d'insightface 0.7.3 contient un DOSSIER RACINE (contrairement
    a buffalo_l) : l'auto-extract pose les .onnx dans .../models/antelopev2/antelopev2/,
    or FaceAnalysis globbe NON-recursivement -> 0 modele charge -> AssertionError
    (`'detection' in self.models`). CHAQUE install fraiche en auto-download est
    touchee, et ca ne s'auto-repare jamais (le dossier externe existe, insightface
    ne re-telecharge pas). On aplatit une fois pour toutes ici."""
    import glob, os, shutil
    root = models_root or os.path.join(os.path.expanduser('~'), '.insightface')
    outer = os.path.join(root, 'models', 'antelopev2')
    inner = os.path.join(outer, 'antelopev2')
    if not os.path.isdir(inner) or glob.glob(os.path.join(outer, '*.onnx')):
        return
    moved = 0
    for f in glob.glob(os.path.join(inner, '*.onnx')):
        shutil.move(f, outer)
        moved += 1
    try:
        os.rmdir(inner)
    except OSError:
        pass  # reliquats (zip...) — sans consequence
    if moved:
        _log(f"[face] repaired nested antelopev2 layout ({moved} model(s) moved up)")


def main() -> int:
    raw = sys.stdin.read()
    try:
        req = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as e:
        print(json.dumps({"ref_ok": False, "results": {}, "error": f"bad json: {e}"})); return 1
    ref = req.get("ref"); images = [str(p) for p in (req.get("images") or [])]
    refs = [str(p) for p in (req.get("refs") or []) if p]
    if ref and ref not in refs:
        refs.insert(0, str(ref))
    models_root = req.get("models_root") or None
    if not ref or not images:
        print(json.dumps({"ref_ok": False, "results": {}, "error": "missing ref/images"})); return 1

    import numpy as np, cv2
    from insightface.app import FaceAnalysis
    _repair_nested_antelopev2(models_root)
    try:
        if models_root:
            app = FaceAnalysis(name='antelopev2', root=models_root,
                               providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
        else:  # pas de models_root configure -> auto-download vers ~/.insightface
            app = FaceAnalysis(name='antelopev2',
                               providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
        app.prepare(ctx_id=0, det_size=(640, 640))
    except Exception as e:
        # Un crash de chargement (modeles absents/corrompus) doit sortir en JSON
        # propre — pas en traceback muet que le parent resume en « pas de JSON ».
        print(json.dumps({"ref_ok": False, "results": {},
                          "error": f"model load failed: {type(e).__name__}: {e}"}))
        return 1
    import onnxruntime as ort
    _log(f"[face] providers: {ort.get_available_providers()}")

    def biggest(faces):
        return max(faces, key=lambda f: (f.bbox[2]-f.bbox[0])*(f.bbox[3]-f.bbox[1])) if faces else None

    def detect(img):
        faces = list(app.get(img) or [])
        if not faces:  # padding rescue : SCRFD rate les gros plans plein cadre
            h, w = img.shape[:2]; pad = int(0.25 * max(h, w))
            faces = list(app.get(cv2.copyMakeBorder(
                img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(0, 0, 0))) or [])
            return faces, pad
        return faces, 0

    def quality(img, f, pad):
        """Measure the pixels the identity model actually used, not the backdrop."""
        h, w = img.shape[:2]
        x1, y1, x2, y2 = [float(v) for v in f.bbox]
        if pad:
            x1 -= pad; x2 -= pad; y1 -= pad; y2 -= pad
        ix1 = max(0, min(w - 1, int(x1))); iy1 = max(0, min(h - 1, int(y1)))
        ix2 = max(ix1 + 1, min(w, int(x2))); iy2 = max(iy1 + 1, min(h, int(y2)))
        crop = img[iy1:iy2, ix1:ix2]
        if crop.size == 0:
            return {"face_sharpness": 0, "face_exposure": 0,
                    "face_clipped": 1.0, "face_width": 0, "face_height": 0}
        grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        sharp_raw = float(cv2.Laplacian(grey, cv2.CV_64F).var())
        sharpness = max(0, min(100, round((max(sharp_raw, 0) ** 0.5) * 3.0)))
        mean = float(np.mean(grey))
        clipped = float(np.mean((grey <= 4) | (grey >= 251)))
        exposure = max(0, min(100, round(100 - abs(mean - 128) / 128 * 70 - clipped * 100)))
        return {"face_sharpness": sharpness, "face_exposure": exposure,
                "face_clipped": round(clipped, 4),
                "face_width": ix2 - ix1, "face_height": iy2 - iy1}

    def analyze(path, identity_emb=None):
        img = cv2.imread(path)
        if img is None: return {"state": "unreadable"}
        h, w = img.shape[:2]
        faces, pad = detect(img)
        if not faces: return {"state": "no_face", "face_count": 0}
        if identity_emb is not None:
            f = max(faces, key=lambda face: float(np.dot(identity_emb, face.normed_embedding)))
        else:
            f = biggest(faces)
        scale = ((w + 2*pad) * (h + 2*pad) / (w * h)) if pad else 1.0
        area = (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1])
        bbox_frac = float(area / (w * h) / scale)
        det = float(f.det_score)
        yaw = float(f.pose[1]) if getattr(f, "pose", None) is not None else 0.0
        state = "scorable"
        if det < DET_MIN: state = "low_det"
        elif bbox_frac < BBOX_MIN: state = "too_small"
        elif abs(yaw) > YAW_MAX: state = "extreme_pose"
        elif len(faces) > 1: state = "multi_face"
        return {"state": state, "det": round(det, 3), "bbox_frac": round(bbox_frac, 4),
                "yaw": round(yaw, 1), "face_count": len(faces),
                **quality(img, f, pad), "_emb": f.normed_embedding}

    ref_embeddings = []
    ref_states = []
    for ref_path in refs:
        ref_res = analyze(ref_path)
        emb = ref_res.pop("_emb", None)
        if emb is not None:
            ref_embeddings.append(emb)
        else:
            ref_states.append(ref_res.get("state"))
    if not ref_embeddings:
        print(json.dumps({"ref_ok": False, "results": {},
                          "error": f"refs unusable: {', '.join(ref_states)}"})); return 1
    ref_emb = np.mean(np.stack(ref_embeddings), axis=0)
    ref_emb = ref_emb / np.linalg.norm(ref_emb)

    results = {}
    for i, p in enumerate(images, 1):
        try:
            r = analyze(p, ref_emb); emb = r.pop("_emb", None)
            if r["state"] in ("scorable", "multi_face") and emb is not None:
                r["sim"] = round(float(np.dot(ref_emb, emb)), 4)
            results[p] = r
            _log(f"[face] {i}/{len(images)} {r['state']} sim={r.get('sim')}")
        except Exception as e:
            results[p] = {"state": "error", "error": str(e)}
            _log(f"[face] {i}/{len(images)} ERROR {e}")
    print(json.dumps({"ref_ok": True, "refs_used": len(ref_embeddings), "results": results}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
