from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from classifier import ClassificationResult, IntentClassifier  # noqa: E402

_ROOT = Path(__file__).parent.parent
STATIC_DIR = Path(__file__).parent / "static"

MODELS: dict[str, IntentClassifier | "BaselineClassifier"] = {}


class BaselineClassifier:
    def __init__(self, pipeline):
        self.pipeline = pipeline

    @classmethod
    def load(cls, path: Path) -> "BaselineClassifier":
        import joblib
        return cls(joblib.load(path))

    def classify(self, text: str) -> ClassificationResult:
        probs = self.pipeline.predict_proba([text])[0]
        label_id = int(probs.argmax())
        return ClassificationResult(
            label="benign" if label_id == 0 else "malicious",
            label_id=label_id,
            prob_benign=float(probs[0]),
            prob_malicious=float(probs[1]),
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    MODELS["distilbert_v1"] = IntentClassifier.load(
        _ROOT / "models" / "distilbert_v1"
    )
    MODELS["roberta_v1"] = IntentClassifier.load(
        _ROOT / "models" / "roberta_v1"
    )
    MODELS["baseline"] = BaselineClassifier.load(
        _ROOT / "models" / "baseline_tfidf_lr.joblib"
    )
    yield


app = FastAPI(title="SentinelAI", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class ClassifyRequest(BaseModel):
    text: str
    model: Literal["distilbert_v1", "roberta_v1", "baseline"] = "distilbert_v1"


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/health")
def health():
    return {"status": "ok", "models_loaded": list(MODELS.keys())}


@app.post("/classify")
def classify(req: ClassifyRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text must not be empty")
    if len(text) > 2000:
        raise HTTPException(status_code=422, detail="text exceeds 2000 characters")
    clf = MODELS.get(req.model)
    if clf is None:
        raise HTTPException(status_code=422, detail=f"unknown model: {req.model}")
    try:
        result = clf.classify(text)
        return {**result.to_dict(), "model": req.model}
    except Exception:
        raise HTTPException(status_code=500, detail="Classification failed")
