"""Export cluster-diagnostic tables for the Power BI dashboard.

The BI layer for this project is not a generic sales dashboard — it is a
*clustering* dashboard. That means the model has to carry the things a
segmentation analyst actually argues about:

- Is K=4 defensible?            -> k_selection.csv (inertia + silhouette per K)
- Do the clusters hold together? -> per-customer silhouette + distance to centroid
- What defines each cluster?     -> centroids.csv in standardized log-RFM space
- Who is about to switch?        -> nearest rival cluster + boundary margin
- Where do the clusters live?    -> country-level and country x segment rollups

Everything is derived from the same artifacts the pipeline already produced, so
the dashboard can never drift from the model that made the segments.

Run:  python -m src.export_cluster_diagnostics
"""

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import silhouette_samples

from src.clustering import CLUSTER_FEATURES, prepare_matrix

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
OUT_DIR = PROJECT_ROOT / "dashboard" / "data"

# A customer whose silhouette is this low sits closer to a rival cluster's
# territory than to the comfortable middle of its own — worth a marketing look.
BORDERLINE_SILHOUETTE = 0.25


def load_segmented() -> pd.DataFrame:
    df = pd.read_parquet(PROCESSED_DIR / "customers_segmented.parquet")
    if "Segment" not in df.columns:
        raise SystemExit("customers_segmented.parquet has no Segment column — run src.clustering first")
    return df


def cluster_geometry(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach per-customer cluster geometry and return (customers, centroids).

    The clustering space is standardized log1p(R/F/M) — identical to the space
    K-Means optimized in, so every distance quoted on the dashboard is the
    distance the algorithm itself saw.
    """
    X, _ = prepare_matrix(df)
    zcols = ["Z_Recency", "Z_Frequency", "Z_Monetary"]
    df = df.copy()
    df[zcols] = X

    segments = sorted(df["Segment"].unique())
    centroids = np.vstack([X[df["Segment"].values == s].mean(axis=0) for s in segments])

    # Distance from every customer to every centroid, in the model's own space.
    dists = np.linalg.norm(X[:, None, :] - centroids[None, :, :], axis=2)
    own_idx = np.array([segments.index(s) for s in df["Segment"]])
    rows = np.arange(len(df))

    own_dist = dists[rows, own_idx]
    masked = dists.copy()
    masked[rows, own_idx] = np.inf
    rival_idx = masked.argmin(axis=1)
    rival_dist = masked[rows, rival_idx]

    df["DistToCentroid"] = own_dist.round(3)
    df["DistToRival"] = rival_dist.round(3)
    df["NearestRival"] = [segments[i] for i in rival_idx]
    # 0 = dead centre of its cluster, 1 = exactly on the boundary between two.
    df["BoundaryMargin"] = (own_dist / (own_dist + rival_dist)).round(3)
    df["Silhouette"] = silhouette_samples(X, own_idx).round(3)
    df["Cohesion"] = np.select(
        [df["Silhouette"] >= 0.50, df["Silhouette"] >= BORDERLINE_SILHOUETTE],
        ["Core", "Settled"],
        default="Borderline",
    )
    df["IsBorderline"] = (df["Cohesion"] == "Borderline").astype(int)

    centroid_long = []
    for s, c in zip(segments, centroids):
        grp = df[df["Segment"] == s]
        for order, (feature, z) in enumerate(zip(CLUSTER_FEATURES, c), start=1):
            centroid_long.append({
                "Segment": s,
                "Feature": feature,
                # Keeps the fingerprint chart in R-F-M reading order instead of
                # the alphabetical order Power BI would otherwise impose.
                "FeatureOrder": order,
                "ZScore": round(float(z), 3),
                "ActualValue": round(float(grp[feature].mean()), 1),
                "Customers": int(len(grp)),
            })
    return df, pd.DataFrame(centroid_long)


def k_selection_table() -> pd.DataFrame:
    scores = pd.read_csv(PROCESSED_DIR / "k_selection_scores.csv")
    chosen = int(scores[scores["k"] >= 3].loc[lambda d: d["silhouette"].idxmax(), "k"])
    scores["Chosen"] = np.where(scores["k"] == chosen, "Chosen K", "Candidate")
    # K=2 wins raw silhouette but only splits active/inactive — unactionable.
    scores["Verdict"] = np.where(
        scores["k"] == 2, "Trivial split (rejected)",
        np.where(scores["k"] == chosen, "Selected", "Considered"),
    )
    scores["silhouette"] = scores["silhouette"].round(4)
    scores["inertia"] = scores["inertia"].round(1)
    return scores.rename(columns={"k": "K", "inertia": "Inertia", "silhouette": "Silhouette"})


def main() -> None:
    # Geography is deliberately NOT pre-aggregated here. The dashboard's maps
    # read Customers[Country] directly so that a segment or cohesion slicer
    # re-filters the map the same way it re-filters every other visual; a
    # pre-rolled country table would silently keep showing all-segment totals.
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = load_segmented()
    customers, centroids = cluster_geometry(df)

    export_cols = [
        "CustomerID", "Segment", "Country", "Recency", "Frequency", "Monetary",
        "AvgOrderValue", "InterPurchaseStd", "ProductDiversity", "TenureDays",
        "Z_Recency", "Z_Frequency", "Z_Monetary", "DistToCentroid", "DistToRival",
        "NearestRival", "BoundaryMargin", "Silhouette", "Cohesion", "IsBorderline",
    ]
    customers = customers[export_cols].round({
        "Recency": 0, "Frequency": 0, "Monetary": 2, "AvgOrderValue": 2,
        "InterPurchaseStd": 1, "ProductDiversity": 0, "TenureDays": 0,
        "Z_Recency": 3, "Z_Frequency": 3, "Z_Monetary": 3,
    })

    outputs = {
        "cluster_customers.csv": customers,
        "cluster_centroids.csv": centroids,
        "k_selection.csv": k_selection_table(),
        "dim_segment.csv": pd.DataFrame({"Segment": sorted(customers["Segment"].unique())}),
        "dim_country.csv": pd.DataFrame({"Country": sorted(customers["Country"].unique())}),
        "dim_cohesion.csv": pd.DataFrame({"Cohesion": ["Core", "Settled", "Borderline"]}),
    }
    for name, frame in outputs.items():
        frame.to_csv(OUT_DIR / name, index=False, encoding="utf-8")
        print(f"{name:26} {len(frame):>6} rows  {list(frame.columns)}")

    borderline = customers[customers["Cohesion"] == "Borderline"]
    print(f"\nborderline customers: {len(borderline)} "
          f"({len(borderline)/len(customers)*100:.1f}%), "
          f"lifetime value at stake ${borderline['Monetary'].sum():,.0f}")
    print(customers.groupby("Segment")["Silhouette"].mean().round(3).to_string())


if __name__ == "__main__":
    main()
