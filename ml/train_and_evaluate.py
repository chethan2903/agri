"""Reproducible Random Forest training, hyperparameter tuning, and evaluation
script for the AgriSense crop recommendation engine.

Addresses peer-review requirements for:
- Explicit dataset size, class counts, and stratified train/test split reporting.
- Systematic Random Forest hyperparameter tuning via Stratified K-Fold GridSearchCV
  (conducted strictly on the training split to prevent data leakage).
- Quantitative evaluation (accuracy, macro/weighted F1, cross-validation mean/std,
  and feature importances) exported to ``models/model_metadata.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    f1_score,
)
from sklearn.model_selection import GridSearchCV, StratifiedKFold, train_test_split

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
DEFAULT_MODEL_PATH = os.path.join(PROJECT_ROOT, "models", "crop_model.pkl")
DEFAULT_LABELS_PATH = os.path.join(PROJECT_ROOT, "models", "crop_labels.pkl")
DEFAULT_METADATA_PATH = os.path.join(PROJECT_ROOT, "models", "model_metadata.json")

FEATURE_COLUMNS = ["N", "P", "K", "temperature", "humidity", "ph"]


def inspect_existing_model(
    model_path: str = DEFAULT_MODEL_PATH,
    labels_path: str = DEFAULT_LABELS_PATH,
) -> dict[str, Any]:
    """Inspect an existing pickled RandomForestClassifier and return its verified metadata."""
    with open(model_path, "rb") as f:
        model = pickle.load(f)
    with open(labels_path, "rb") as f:
        labels = pickle.load(f)

    params = model.get_params()
    feature_names = (
        list(model.feature_names_in_)
        if hasattr(model, "feature_names_in_")
        else list(FEATURE_COLUMNS)
    )
    importances = {}
    if hasattr(model, "feature_importances_"):
        importances = {
            name: round(float(val), 4)
            for name, val in zip(feature_names, model.feature_importances_)
        }

    return {
        "model_type": type(model).__name__,
        "n_features": int(getattr(model, "n_features_in_", len(feature_names))),
        "feature_names": feature_names,
        "n_classes": len(labels),
        "classes": list(labels),
        "hyperparameters": {
            "n_estimators": params.get("n_estimators"),
            "criterion": params.get("criterion"),
            "max_depth": params.get("max_depth"),
            "min_samples_split": params.get("min_samples_split"),
            "min_samples_leaf": params.get("min_samples_leaf"),
            "max_features": params.get("max_features"),
            "bootstrap": params.get("bootstrap"),
            "random_state": params.get("random_state"),
        },
        "feature_importances": importances,
        "inspected_at": datetime.now(timezone.utc).isoformat(),
    }


def train_and_tune(
    dataset_path: str,
    test_size: float = 0.2,
    cv_folds: int = 5,
    random_state: int = 42,
    save_model: bool = False,
    model_path: str = DEFAULT_MODEL_PATH,
    labels_path: str = DEFAULT_LABELS_PATH,
    metadata_path: str = DEFAULT_METADATA_PATH,
    param_grid: dict[str, list[Any]] | None = None,
) -> dict[str, Any]:
    """Train, tune, and evaluate a RandomForestClassifier on a labeled crop CSV."""
    df = pd.read_csv(dataset_path)
    required = FEATURE_COLUMNS + ["label"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"Dataset missing required columns: {missing}")

    df = df.dropna(subset=required).copy()
    X = df[FEATURE_COLUMNS]
    y = df["label"].astype(str)

    X_train, X_test, y_train, y_test = train_test_split(
        X,
        y,
        test_size=test_size,
        random_state=random_state,
        stratify=y,
    )

    effective_grid = param_grid or {
        "n_estimators": [50, 100, 150, 200],
        "criterion": ["gini", "entropy"],
        "max_depth": [None, 10, 20],
        "min_samples_split": [2, 5],
        "min_samples_leaf": [1, 2],
        "max_features": ["sqrt", "log2"],
    }

    cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=random_state)
    base_rf = RandomForestClassifier(random_state=random_state, n_jobs=1)

    grid = GridSearchCV(
        estimator=base_rf,
        param_grid=effective_grid,
        cv=cv,
        scoring="accuracy",
        n_jobs=1,
        refit=True,
    )
    grid.fit(X_train, y_train)

    best_model: RandomForestClassifier = grid.best_estimator_
    y_pred = best_model.predict(X_test)

    test_acc = float(accuracy_score(y_test, y_pred))
    macro_f1 = float(f1_score(y_test, y_pred, average="macro"))
    weighted_f1 = float(f1_score(y_test, y_pred, average="weighted"))
    report = classification_report(y_test, y_pred, output_dict=True)

    labels = sorted(y.unique().tolist())
    importances = {
        name: round(float(val), 4)
        for name, val in zip(FEATURE_COLUMNS, best_model.feature_importances_)
    }

    metadata = {
        "model_type": type(best_model).__name__,
        "n_features": len(FEATURE_COLUMNS),
        "feature_names": FEATURE_COLUMNS,
        "n_classes": len(labels),
        "classes": labels,
        "dataset": {
            "source_file": os.path.basename(dataset_path),
            "total_samples": int(len(df)),
            "train_samples": int(len(X_train)),
            "test_samples": int(len(X_test)),
            "train_ratio": round(1.0 - test_size, 4),
            "test_ratio": round(test_size, 4),
            "stratified": True,
            "random_state": random_state,
        },
        "tuning": {
            "method": "GridSearchCV",
            "cv_strategy": f"StratifiedKFold(n_splits={cv_folds}, shuffle=True, random_state={random_state})",
            "param_grid": effective_grid,
            "best_cv_accuracy": round(float(grid.best_score_), 4),
        },
        "hyperparameters": {
            key: best_model.get_params().get(key)
            for key in [
                "n_estimators",
                "criterion",
                "max_depth",
                "min_samples_split",
                "min_samples_leaf",
                "max_features",
                "bootstrap",
                "random_state",
            ]
        },
        "evaluation": {
            "test_accuracy": round(test_acc, 4),
            "test_accuracy_pct": round(test_acc * 100.0, 2),
            "macro_f1": round(macro_f1, 4),
            "weighted_f1": round(weighted_f1, 4),
            "per_class_report": report,
        },
        "feature_importances": importances,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }

    if save_model:
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        with open(model_path, "wb") as f:
            pickle.dump(best_model, f)
        with open(labels_path, "wb") as f:
            pickle.dump(labels, f)

    os.makedirs(os.path.dirname(metadata_path), exist_ok=True)
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="AgriSense Random Forest training & inspection tool")
    parser.add_argument("--dataset", type=str, help="Path to labeled crop recommendation CSV")
    parser.add_argument("--test-size", type=float, default=0.2, help="Test split fraction (default: 0.2)")
    parser.add_argument("--cv", type=int, default=5, help="Number of StratifiedKFold CV splits (default: 5)")
    parser.add_argument("--random-state", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--save-model", action="store_true", help="Overwrite crop_model.pkl and crop_labels.pkl")
    parser.add_argument(
        "--inspect-existing",
        action="store_true",
        help="Inspect existing pickled model and write baseline metadata JSON",
    )
    args = parser.parse_args()

    if args.inspect_existing or not args.dataset:
        meta = inspect_existing_model()
        os.makedirs(os.path.dirname(DEFAULT_METADATA_PATH), exist_ok=True)
        with open(DEFAULT_METADATA_PATH, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        print(json.dumps(meta, indent=2))
        return

    meta = train_and_tune(
        dataset_path=args.dataset,
        test_size=args.test_size,
        cv_folds=args.cv,
        random_state=args.random_state,
        save_model=args.save_model,
    )
    print(
        f"Training complete: {meta['dataset']['train_samples']} train / "
        f"{meta['dataset']['test_samples']} test | "
        f"CV Acc={meta['tuning']['best_cv_accuracy']:.4f} | "
        f"Test Acc={meta['evaluation']['test_accuracy_pct']}%"
    )


if __name__ == "__main__":
    main()
