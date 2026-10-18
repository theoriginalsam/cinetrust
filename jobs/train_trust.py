"""Train the anti-farming trust model, red-team it, and register it in Unity Catalog.

Champion/challenger: the new version only gets the `champion` alias if its average precision
on the injected-farm evaluation is at least as good as the current champion's on the same data.
"""

import argparse
import sys
from pathlib import Path


def _default_src() -> str:
    try:
        return str(Path(__file__).resolve().parents[1] / "src")
    except NameError:
        return "src"


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", default=_default_src())
    p.add_argument("--catalog", default="workspace")
    p.add_argument("--schema", default="cinetrust")
    p.add_argument("--model-name", default="trust_model")
    p.add_argument("--experiment", help="MLflow experiment path (default: /Users/<you>/cinetrust)")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--min-reviews", type=int, default=50)
    args = p.parse_args(argv)
    sys.path.insert(0, args.src)

    import mlflow
    import sklearn
    from mlflow.models import infer_signature
    from mlflow.tracking import MlflowClient

    from cinetrust.evaluation import evaluate
    from cinetrust.features import MODEL_FEATURES, build_features
    from cinetrust.mlflow_model import TrustPyfunc
    from cinetrust.platform import fq, get_spark
    from cinetrust.trust import TrustModel

    spark = get_spark()
    reviews = spark.table(fq(args.catalog, args.schema, "silver_reviews")).toPandas()
    scores = spark.table(fq(args.catalog, args.schema, "silver_source_scores")).toPandas()
    if len(reviews) < args.min_reviews:
        raise SystemExit(f"Only {len(reviews)} reviews in silver; run the daily job a few times first.")

    feats = build_features(reviews, scores)
    model = TrustModel(random_state=args.seed).fit(feats)
    report = evaluate(model.predict, reviews, scores, seed=args.seed)
    print(report["metrics"])

    mlflow.set_registry_uri("databricks-uc")
    user = spark.sql("SELECT current_user()").first()[0]
    mlflow.set_experiment(args.experiment or f"/Users/{user}/cinetrust")
    name = f"{args.catalog}.{args.schema}.{args.model_name}"
    client = MlflowClient()

    X = feats[MODEL_FEATURES].astype(float)
    with mlflow.start_run(run_name="trust-model") as run:
        mlflow.log_params({**model.params(), "n_reviews": len(feats), "n_sources": reviews["source"].nunique()})
        mlflow.log_metrics(report["metrics"])
        mlflow.log_dict(report, "redteam_evaluation.json")
        info = mlflow.pyfunc.log_model(
            "model",
            python_model=TrustPyfunc(model),
            code_paths=[str(Path(args.src) / "cinetrust")],
            signature=infer_signature(X.head(100), model.predict(feats.head(100))),
            input_example=X.head(3),
            pip_requirements=[f"scikit-learn=={sklearn.__version__}", "pandas", "numpy"],
        )
        version = mlflow.register_model(info.model_uri, name).version

    try:
        client.get_model_version_by_alias(name, "champion")
        champion = mlflow.pyfunc.load_model(f"models:/{name}@champion")
        champ_ap = evaluate(champion.predict, reviews, scores, seed=args.seed)["metrics"]["average_precision"]
    except Exception:
        champ_ap = None

    promote = champ_ap is None or report["metrics"]["average_precision"] >= champ_ap
    client.set_model_version_tag(name, version, "redteam_average_precision",
                                 str(report["metrics"]["average_precision"]))
    if promote:
        client.set_registered_model_alias(name, "champion", version)
    print(f"{name} v{version} (run {run.info.run_id}): champion AP={champ_ap} -> "
          f"{'promoted' if promote else 'kept current champion'}")


if __name__ == "__main__":
    main()
