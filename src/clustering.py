"""Clustering: scaling, K selection (elbow + silhouette), K-Means, and
business-language segment naming.

Scaling note (a commonly skipped step): Frequency and Monetary are heavily
right-skewed (a few wholesale buyers spend 100x the median). K-Means uses
Euclidean distance, so without a log-transform those whales dominate every
centroid. We cluster on log1p(R/F/M) -> StandardScaler.
"""

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
RANDOM_STATE = 42

CLUSTER_FEATURES = ["Recency", "Frequency", "Monetary"]


def prepare_matrix(rfm: pd.DataFrame):
    """log1p -> standardize the RFM columns; returns (X, fitted scaler)."""
    logged = np.log1p(rfm[CLUSTER_FEATURES])
    scaler = StandardScaler().fit(logged)
    return scaler.transform(logged), scaler


def k_selection_scores(X: np.ndarray, k_range=range(2, 9)) -> pd.DataFrame:
    """Inertia (elbow) + silhouette for each K. Silhouette uses a 5k sample
    for speed — its ranking stabilizes well below full size."""
    rng = np.random.RandomState(RANDOM_STATE)
    sample_idx = rng.choice(len(X), size=min(5000, len(X)), replace=False)
    rows = []
    for k in k_range:
        km = KMeans(n_clusters=k, n_init=10, random_state=RANDOM_STATE).fit(X)
        sil = silhouette_score(X[sample_idx], km.labels_[sample_idx])
        rows.append({"k": k, "inertia": km.inertia_, "silhouette": sil})
    return pd.DataFrame(rows)


def fit_kmeans(X: np.ndarray, k: int) -> KMeans:
    return KMeans(n_clusters=k, n_init=25, random_state=RANDOM_STATE).fit(X)


def name_segments(rfm: pd.DataFrame, cluster_col: str = "Cluster") -> dict:
    """Map cluster ids -> business names from their R/F/M profile.

    Rules relative to the population median:
    - recent + frequent + high spend  -> Champions
    - recent + frequent               -> Loyal Customers
    - recent + infrequent             -> New Customers
    - lapsed + was high spend         -> At Risk (worth saving)
    - lapsed + low engagement         -> Hibernating
    """
    med = rfm[CLUSTER_FEATURES].median()
    names = {}
    for cid, grp in rfm.groupby(cluster_col):
        r, f, m = grp["Recency"].mean(), grp["Frequency"].mean(), grp["Monetary"].mean()
        recent, frequent, rich = r < med["Recency"], f > med["Frequency"], m > med["Monetary"]
        if recent and frequent and rich:
            name = "Champions"
        elif recent and frequent:
            name = "Loyal Customers"
        elif recent:
            name = "New Customers"
        elif rich:
            name = "At Risk"
        else:
            name = "Hibernating"
        names[cid] = name

    # De-duplicate (two clusters can hit the same rule at higher K)
    seen = {}
    for cid in sorted(names, key=lambda c: rfm.loc[rfm[cluster_col] == c, "Monetary"].mean(),
                      reverse=True):
        base = names[cid]
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            names[cid] = f"{base} {seen[base]}"
    return names


def profile_segments(rfm: pd.DataFrame, seg_col: str = "Segment") -> pd.DataFrame:
    """Per-segment profile: size, revenue share, R/F/M and behavior means."""
    total_rev = rfm["Monetary"].sum()
    prof = rfm.groupby(seg_col).agg(
        Customers=("CustomerID", "count"),
        AvgRecencyDays=("Recency", "mean"),
        AvgFrequency=("Frequency", "mean"),
        AvgMonetary=("Monetary", "mean"),
        TotalRevenue=("Monetary", "sum"),
        AvgOrderValue=("AvgOrderValue", "mean"),
        AvgProductDiversity=("ProductDiversity", "mean"),
    ).round(1)
    prof["RevenueShare"] = (prof["TotalRevenue"] / total_rev * 100).round(1)
    prof["CustomerShare"] = (prof["Customers"] / len(rfm) * 100).round(1)
    return prof.sort_values("TotalRevenue", ascending=False)


def main(k: int | None = None) -> None:
    rfm = pd.read_parquet(PROCESSED_DIR / "rfm_features.parquet")
    X, _ = prepare_matrix(rfm)

    scores = k_selection_scores(X)
    scores.to_csv(PROCESSED_DIR / "k_selection_scores.csv", index=False)
    if k is None:
        # K=2 always wins raw silhouette on log-RFM but only separates
        # "active vs inactive" — a trivial, unactionable split. We therefore
        # require K >= 3 and take the silhouette maximum there, which lands
        # on the local silhouette peak that also sits in the elbow region.
        nontrivial = scores[scores["k"] >= 3]
        k = int(nontrivial.loc[nontrivial["silhouette"].idxmax(), "k"])
    print(f"K selection scores:\n{scores.to_string(index=False)}")
    print(f"chosen K = {k} (silhouette max among K>=3; K=2 is the trivial "
          f"active/inactive split — see notebook 03 for the full argument)")

    km = fit_kmeans(X, k)
    rfm["Cluster"] = km.labels_
    names = name_segments(rfm)
    rfm["Segment"] = rfm["Cluster"].map(names)
    print("segment names:", names)

    rfm.to_parquet(PROCESSED_DIR / "customers_segmented.parquet", index=False)
    prof = profile_segments(rfm)
    prof.to_csv(PROCESSED_DIR / "segment_profile.csv")
    print(prof.to_string())


if __name__ == "__main__":
    main()
