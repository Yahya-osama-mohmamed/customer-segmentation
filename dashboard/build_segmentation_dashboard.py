# -*- coding: utf-8 -*-
"""Build the Cluster Intelligence Power BI dashboard (PBIP/PBIR).

This is deliberately NOT a generic sales dashboard. Every page answers a
question a segmentation owner actually has to defend:

  1. Cluster Anatomy   — are these four clusters real, and why K=4?
  2. Cluster Space     — where does each customer sit in the model's own space?
  3. Cluster Geography — where on the map does each cluster concentrate?
  4. Boundary Watch    — who is about to drift into another cluster, and what
                         is that worth?

All visuals read the same customer-grain table, so a slicer anywhere
re-filters maps, scatters and diagnostics together.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pbip_lib import (
    col, meas, agg, proj, visual, card, slicer, textbox, make_theme, azure_map,
    default_color, category_colors,
    table_from_csv, build_model, validate_report_against_model, write_project,
)

DATA = Path(r"C:\Users\pc\Downloads\data\customer-segmentation\dashboard\data")
OUT = Path(r"C:\Users\pc\Downloads\data\customer-segmentation\dashboard\SegmentationExplorer")
THEME_SRC = Path(__file__).parent / "pbir_ref" / "theme_CY24SU10.json"

# ---- Palette (Color Hunt 8AA624 / DBE4C9 / FFFFF0 / FEA405) ----
# Clusters are coloured on a value ramp rather than four arbitrary hues: amber
# marks the cluster that funds the business, olive the active middle, pale sage
# the dormant tail. Segment ranking is then readable without the legend.
OLIVE = "#8AA624"   # primary brand
SAGE = "#DBE4C9"    # palest step / borders
IVORY = "#FFFFF0"   # page background
AMBER = "#FEA405"   # accent — Champions and anything needing attention
DARK = "#4E5E14"    # darkened olive: white header text needs 7:1 contrast,
                    # which #8AA624 alone cannot carry
LEAF = "#B5CC5E"    # ramp step between OLIVE and SAGE

INDIGO = DARK       # header band
PURPLE = OLIVE      # primary accent
TEAL = LEAF
GOLD = AMBER
RED = OLIVE
GREY = SAGE
PAGE_BG = IVORY

SEGMENT_COLORS = {"Champions": AMBER, "At Risk": OLIVE,
                  "New Customers": LEAF, "Hibernating": SAGE}
# Amber marks the group that needs action, so Borderline reads first.
COHESION_COLORS = {"Core": SAGE, "Settled": OLIVE, "Borderline": AMBER}

theme = make_theme(
    "SegmentationTheme",
    data_colors=[OLIVE, AMBER, LEAF, SAGE, DARK, "#FFCE6B", "#6E8A1E", "#EFF3E4"],
    page_bg=PAGE_BG, fg=DARK, accent=OLIVE,
    border_color=SAGE,
)

M, G, W = 24, 12, 1280
HEADER = dict(x=0, y=0, w=W, h=54)
SLICER_Y, SLICER_H, SLICER_W = 62, 56, 196
RAIL_X, RAIL_W, CONTENT_X = 24, 180, 216


def header_band(name, title, subtitle):
    return textbox(name, title, **HEADER, size="16pt", color="#FFFFFF",
                   bg_color=INDIGO, subtitle=subtitle, subtitle_color="#B8B3EC")


def kpi_row(cards_spec, y=124, h=96, x0=M, x1=W - M):
    n = len(cards_spec)
    w = (x1 - x0 - (n - 1) * G) // n
    return [card(name, field, x0 + i * (w + G), y, w, h, title=title)
            for i, (name, field, title) in enumerate(cards_spec)]


def slicer_row(slicers_spec, y=SLICER_Y):
    n = len(slicers_spec)
    return [slicer(name, field, W - M - (n - i) * SLICER_W - (n - i - 1) * G, y,
                   SLICER_W, SLICER_H, title=title, dropdown=True)
            for i, (name, field, title) in enumerate(slicers_spec)]


# ============================================================================
# Semantic model — customer grain plus the clustering diagnostics
# ============================================================================

customers = table_from_csv(
    "Customers", DATA / "cluster_customers.csv",
    types={"CustomerID": "int64", "Segment": "string", "Country": "string",
           "Recency": "int64", "Frequency": "double", "Monetary": "double",
           "AvgOrderValue": "double", "InterPurchaseStd": "double",
           "ProductDiversity": "double", "TenureDays": "double",
           "Z_Recency": "double", "Z_Frequency": "double", "Z_Monetary": "double",
           "DistToCentroid": "double", "DistToRival": "double",
           "NearestRival": "string", "BoundaryMargin": "double",
           "Silhouette": "double", "Cohesion": "string", "IsBorderline": "double"},
    # Bing only geocodes columns whose data category marks them as geographic.
    data_categories={"Country": "Country"},
    format_strings={"Monetary": "$#,0", "AvgOrderValue": "$#,0.00",
                    "CustomerID": "0", "Recency": "#,0", "Frequency": "#,0",
                    "Silhouette": "0.000", "BoundaryMargin": "0.000",
                    "DistToCentroid": "0.00", "DistToRival": "0.00"},
    measures=[
        {"name": "Total Customers", "expression": "COUNTROWS('Customers')", "formatString": "#,0"},
        {"name": "Lifetime Revenue", "expression": "SUM('Customers'[Monetary])", "formatString": "$#,0"},
        {"name": "Avg Customer Value", "expression": "AVERAGE('Customers'[Monetary])", "formatString": "$#,0"},
        {"name": "Avg Recency (days)", "expression": "AVERAGE('Customers'[Recency])", "formatString": "0.0"},
        {"name": "Avg Frequency (orders)", "expression": "AVERAGE('Customers'[Frequency])", "formatString": "0.0"},
        {"name": "Avg Silhouette", "expression": "AVERAGE('Customers'[Silhouette])", "formatString": "0.000"},
        {"name": "Avg Distance to Centroid", "expression": "AVERAGE('Customers'[DistToCentroid])", "formatString": "0.00"},
        {"name": "Avg Boundary Margin", "expression": "AVERAGE('Customers'[BoundaryMargin])", "formatString": "0.000"},
        {"name": "Borderline Customers", "expression": "SUM('Customers'[IsBorderline])", "formatString": "#,0"},
        {"name": "Borderline %",
         "expression": "DIVIDE(SUM('Customers'[IsBorderline]), COUNTROWS('Customers')) * 100",
         "formatString": "0.0"},
        {"name": "Value at Stake",
         "expression": "CALCULATE(SUM('Customers'[Monetary]), 'Customers'[Cohesion] = \"Borderline\")",
         "formatString": "$#,0"},
        {"name": "Clusters (K)", "expression": "DISTINCTCOUNT('Customers'[Segment])", "formatString": "0"},
        {"name": "Countries", "expression": "DISTINCTCOUNT('Customers'[Country])", "formatString": "0"},
        {"name": "Champion Share %",
         "expression": "DIVIDE(CALCULATE(COUNTROWS('Customers'), 'Customers'[Segment] = \"Champions\"), COUNTROWS('Customers')) * 100",
         "formatString": "0.0"},
        {"name": "Champions at the Edge",
         "expression": "CALCULATE(COUNTROWS('Customers'), 'Customers'[Segment] = \"Champions\", 'Customers'[Cohesion] = \"Borderline\")",
         "formatString": "#,0"},
        {"name": "Champion Value at Risk",
         "expression": "CALCULATE(SUM('Customers'[Monetary]), 'Customers'[Segment] = \"Champions\", 'Customers'[Cohesion] = \"Borderline\")",
         "formatString": "$#,0"},
        {"name": "Revenue Share %",
         "expression": "DIVIDE(SUM('Customers'[Monetary]), CALCULATE(SUM('Customers'[Monetary]), ALL('Customers'))) * 100",
         "formatString": "0.0"},
    ],
)

centroids = table_from_csv(
    "Centroids", DATA / "cluster_centroids.csv",
    types={"Segment": "string", "Feature": "string", "FeatureOrder": "int64",
           "ZScore": "double", "ActualValue": "double", "Customers": "double"},
    sort_by={"Feature": "FeatureOrder"},
    format_strings={"ZScore": "0.00"},
)

kselection = table_from_csv(
    "KSelection", DATA / "k_selection.csv",
    types={"K": "double", "Inertia": "double", "Silhouette": "double",
           "Chosen": "string", "Verdict": "string"},
    format_strings={"K": "0", "Silhouette": "0.000", "Inertia": "#,0"},
    measures=[
        {"name": "Chosen K",
         "expression": "MAXX(FILTER(ALL('KSelection'), 'KSelection'[Verdict] = \"Selected\"), 'KSelection'[K])",
         "formatString": "0"},
        {"name": "Silhouette at Chosen K",
         "expression": "MAXX(FILTER(ALL('KSelection'), 'KSelection'[Verdict] = \"Selected\"), 'KSelection'[Silhouette])",
         "formatString": "0.000"},
    ],
)

dim_segment = table_from_csv("DimSegment", DATA / "dim_segment.csv",
                             types={"Segment": "string"})
dim_country = table_from_csv("DimCountry", DATA / "dim_country.csv",
                             types={"Country": "string"},
                             data_categories={"Country": "Country"})
dim_cohesion = table_from_csv("DimCohesion", DATA / "dim_cohesion.csv",
                              types={"Cohesion": "string"})

model = build_model(
    "SegmentationExplorer",
    [customers, centroids, kselection, dim_segment, dim_country, dim_cohesion],
    relationships=[
        ("Customers", "Segment", "DimSegment", "Segment"),
        ("Customers", "Country", "DimCountry", "Country"),
        ("Customers", "Cohesion", "DimCohesion", "Cohesion"),
        ("Centroids", "Segment", "DimSegment", "Segment"),
    ],
)

SEG = ("DimSegment", "Segment")
COH = ("DimCohesion", "Cohesion")
CTRY = ("DimCountry", "Country")

# ============================================================================
# Page 1 — Cluster Anatomy: are these clusters real?
# ============================================================================

pg1 = [
    header_band("h1", "Cluster Anatomy — Are These Four Segments Real?",
                "K chosen by silhouette among non-trivial K\u22653; K=2 rejected as the "
                "unactionable active/inactive split."),
    *slicer_row([("sl1_segment", col(*SEG), "Segment")]),
    *kpi_row([
        ("k1_k", meas("KSelection", "Chosen K"), "Clusters (K)"),
        ("k1_cust", meas("Customers", "Total Customers"), "Customers Clustered"),
        ("k1_sil_k", meas("KSelection", "Silhouette at Chosen K"), "Silhouette at Chosen K"),
        ("k1_sil", meas("Customers", "Avg Silhouette"), "Avg Silhouette (customers)"),
        ("k1_border", meas("Customers", "Borderline %"), "Borderline % of Base"),
    ]),

    visual("l1_sil", "lineChart", 24, 228, 404, 240,
           roles={"Category": [proj(col("KSelection", "K"))],
                  "Y": [proj(agg("KSelection", "Silhouette", 1))]},
           title="Silhouette by K — peak at K=4 once the trivial K=2 split is excluded",
           sort=(col("KSelection", "K"), "Ascending"),
           objects=default_color(PURPLE)),
    visual("l1_inertia", "lineChart", 440, 228, 404, 240,
           roles={"Category": [proj(col("KSelection", "K"))],
                  "Y": [proj(agg("KSelection", "Inertia", 1))]},
           title="Inertia (elbow) — returns flatten after K=4",
           sort=(col("KSelection", "K"), "Ascending"),
           objects=default_color(TEAL)),
    visual("b1_sil_seg", "clusteredBarChart", 856, 228, 400, 240,
           roles={"Category": [proj(col(*SEG))],
                  "Y": [proj(meas("Customers", "Avg Silhouette"))]},
           title="Cluster cohesion — average silhouette per cluster",
           sort=(meas("Customers", "Avg Silhouette"), "Descending"),
           objects=category_colors(*SEG, SEGMENT_COLORS)),

    visual("b1_fingerprint", "clusteredColumnChart", 24, 476, 700, 220,
           roles={"Category": [proj(col("Centroids", "Feature"))],
                  "Series": [proj(col("Centroids", "Segment"))],
                  "Y": [proj(agg("Centroids", "ZScore", 1))]},
           title="Centroid fingerprint — standardized log-RFM (0 = population average)",
           objects=category_colors("Centroids", "Segment", SEGMENT_COLORS)),
    visual("t1_profile", "tableEx", 736, 476, 520, 220,
           roles={"Values": [
               proj(col(*SEG)),
               proj(meas("Customers", "Total Customers"), display="Customers"),
               proj(meas("Customers", "Avg Recency (days)"), display="Recency"),
               proj(meas("Customers", "Avg Frequency (orders)"), display="Orders"),
               proj(meas("Customers", "Avg Customer Value"), display="Avg Value"),
               proj(meas("Customers", "Avg Silhouette"), display="Silhouette"),
           ]},
           title="Cluster profile — the four centroids in business units",
           sort=(meas("Customers", "Avg Customer Value"), "Descending")),
]

# ============================================================================
# Page 2 — Cluster Space: every customer as a point
# ============================================================================

pg2 = [
    header_band("h2", "Cluster Space — Every Customer as a Point",
                "Plotted in the standardized log-RFM space K-Means actually optimized in. "
                "Bubble size = lifetime value."),
    slicer("sl2_segment", col(*SEG), RAIL_X, 64, RAIL_W, 172, title="Segment"),
    slicer("sl2_cohesion", col(*COH), RAIL_X, 244, RAIL_W, 146, title="Cluster cohesion"),
    slicer("sl2_country", col(*CTRY), RAIL_X, 398, RAIL_W, 60, title="Country", dropdown=True),

    *kpi_row([
        ("k2_cust", meas("Customers", "Total Customers"), "Customers in View"),
        ("k2_sil", meas("Customers", "Avg Silhouette"), "Avg Silhouette"),
        ("k2_dist", meas("Customers", "Avg Distance to Centroid"), "Avg Distance to Centroid"),
        ("k2_margin", meas("Customers", "Avg Boundary Margin"), "Avg Boundary Margin"),
    ], y=64, x0=CONTENT_X),

    visual("s2_rf", "scatterChart", CONTENT_X, 172, 620, 288,
           roles={"Category": [proj(col("Customers", "CustomerID"))],
                  "Series": [proj(col(*SEG))],
                  "X": [proj(agg("Customers", "Z_Recency", 1))],
                  "Y": [proj(agg("Customers", "Z_Frequency", 1))],
                  "Size": [proj(agg("Customers", "Monetary", 0))]},
           title="Recency vs Frequency (standardized) — the plane the clusters split on",
           objects=category_colors(*SEG, SEGMENT_COLORS)),
    visual("s2_fm", "scatterChart", 848, 172, 408, 288,
           roles={"Category": [proj(col("Customers", "CustomerID"))],
                  "Series": [proj(col(*SEG))],
                  "X": [proj(agg("Customers", "Z_Frequency", 1))],
                  "Y": [proj(agg("Customers", "Z_Monetary", 1))]},
           title="Frequency vs Monetary — value axis",
           objects=category_colors(*SEG, SEGMENT_COLORS)),

    visual("s2_edge", "scatterChart", CONTENT_X, 472, 620, 224,
           roles={"Category": [proj(col("Customers", "CustomerID"))],
                  "Series": [proj(col(*COH))],
                  "X": [proj(agg("Customers", "BoundaryMargin", 1))],
                  "Y": [proj(agg("Customers", "Monetary", 0))]},
           title="Boundary margin vs lifetime value — top-right = valuable and unstable",
           objects=category_colors(*COH, COHESION_COLORS)),
    visual("b2_cohesion", "hundredPercentStackedColumnChart", 848, 472, 408, 224,
           roles={"Category": [proj(col(*SEG))],
                  "Series": [proj(col(*COH))],
                  "Y": [proj(meas("Customers", "Total Customers"))]},
           title="How solidly each cluster holds its members",
           objects=category_colors(*COH, COHESION_COLORS)),
]

# ============================================================================
# Page 3 — Cluster Geography: where the clusters live
# ============================================================================

pg3 = [
    header_band("h3", "Cluster Geography — Where Each Segment Lives",
                "Maps read the customer table directly, so every slicer re-filters the "
                "geography exactly like the rest of the report."),
    *slicer_row([("sl3_segment", col(*SEG), "Segment"),
                 ("sl3_cohesion", col(*COH), "Cluster cohesion")]),
    *kpi_row([
        ("k3_countries", meas("Customers", "Countries"), "Countries"),
        ("k3_cust", meas("Customers", "Total Customers"), "Customers"),
        ("k3_rev", meas("Customers", "Lifetime Revenue"), "Lifetime Revenue"),
        ("k3_champ", meas("Customers", "Champion Share %"), "Champion Share %"),
        ("k3_value", meas("Customers", "Avg Customer Value"), "Avg Customer Value"),
    ]),

    # 480x240 keeps the map close to the 2:1 aspect of a world projection, so
    # the basemap does not tile sideways into repeated copies of the globe.
    visual("m3_filled", "filledMap", 24, 228, 480, 240,
           roles={"Category": [proj(col(*CTRY))],
                  "Gradient": [proj(meas("Customers", "Lifetime Revenue"))]},
           title="Lifetime revenue by country — deeper colour = more revenue"),
    azure_map("m3_bubbles", 516, 228, 480, 240,
              roles={"Category": [proj(col(*CTRY))],
                     "Series": [proj(col(*SEG))],
                     "Size": [proj(meas("Customers", "Total Customers"))]},
              title="Cluster mix by country — bubble size = customers, colour = segment",
              colors=category_colors(*SEG, SEGMENT_COLORS)),
    visual("t3_top", "tableEx", 1008, 228, 248, 240,
           roles={"Values": [
               proj(col(*CTRY)),
               proj(meas("Customers", "Lifetime Revenue"), display="Revenue"),
           ]},
           title="Revenue league table",
           sort=(meas("Customers", "Lifetime Revenue"), "Descending")),

    visual("b3_champ", "clusteredBarChart", 24, 476, 400, 220,
           roles={"Category": [proj(col(*CTRY))],
                  "Y": [proj(meas("Customers", "Champion Share %"))]},
           title="Champion density — % of a country's customers that are Champions",
           sort=(meas("Customers", "Champion Share %"), "Descending"),
           objects=default_color(GOLD)),
    visual("b3_value", "clusteredBarChart", 436, 476, 400, 220,
           roles={"Category": [proj(col(*CTRY))],
                  "Y": [proj(meas("Customers", "Avg Customer Value"))]},
           title="Avg lifetime value per customer by country",
           sort=(meas("Customers", "Avg Customer Value"), "Descending"),
           objects=default_color(PURPLE)),
    visual("t3_matrix", "pivotTable", 848, 476, 408, 220,
           roles={"Rows": [proj(col(*CTRY))],
                  "Columns": [proj(col(*SEG))],
                  "Values": [proj(meas("Customers", "Total Customers"))]},
           title="Customers by country x cluster"),
]

# ============================================================================
# Page 4 — Boundary Watch: who is about to change cluster
# ============================================================================

pg4 = [
    header_band("h4", "Boundary Watch — Who Is About to Change Cluster",
                "Customers whose silhouette is below 0.25 sit nearer a rival centroid than "
                "their own cluster's comfortable middle."),
    slicer("sl4_segment", col(*SEG), RAIL_X, 64, RAIL_W, 172, title="Segment"),
    slicer("sl4_cohesion", col(*COH), RAIL_X, 244, RAIL_W, 146, title="Cluster cohesion"),
    slicer("sl4_country", col(*CTRY), RAIL_X, 398, RAIL_W, 60, title="Country", dropdown=True),
    textbox("tb4_playbook", "Retention playbook",
            RAIL_X, 466, RAIL_W, 230, size="10pt", color=INDIGO, bg_color="#FFFFFF",
            subtitle=("Champions \u2192 At Risk: call before the next order gap.  "
                      "\u2022  At Risk \u2192 Hibernating: win-back offer now, while "
                      "they still recognise the brand.  \u2022  New \u2192 Champions: "
                      "nurture, the cheapest growth in the file.  \u2022  Stable "
                      "Hibernating: stop spending."),
            subtitle_color="#53606E"),

    *kpi_row([
        ("k4_border", meas("Customers", "Borderline Customers"), "Borderline Customers"),
        ("k4_stake", meas("Customers", "Value at Stake"), "Lifetime Value at Stake"),
        ("k4_champ", meas("Customers", "Champions at the Edge"), "Champions at the Edge"),
        ("k4_champval", meas("Customers", "Champion Value at Risk"), "Champion Value at Risk"),
    ], y=64, x0=CONTENT_X),

    visual("t4_matrix", "pivotTable", CONTENT_X, 172, 500, 264,
           roles={"Rows": [proj(col(*SEG))],
                  "Columns": [proj(col("Customers", "NearestRival"))],
                  "Values": [proj(meas("Customers", "Total Customers"))]},
           title="Drift map — current cluster (rows) vs nearest rival cluster (columns)"),
    visual("b4_stake", "clusteredBarChart", 728, 172, 528, 264,
           roles={"Category": [proj(col(*SEG))],
                  "Y": [proj(meas("Customers", "Value at Stake"))]},
           title="Lifetime value sitting on a cluster boundary, by segment",
           sort=(meas("Customers", "Value at Stake"), "Descending"),
           objects=category_colors(*SEG, SEGMENT_COLORS)),

    visual("t4_list", "tableEx", CONTENT_X, 440, 1040, 256,
           roles={"Values": [
               proj(col("Customers", "CustomerID")),
               proj(col("Customers", "Segment")),
               proj(col("Customers", "NearestRival"), display="Drifting toward"),
               proj(agg("Customers", "BoundaryMargin", 1), display="Boundary margin"),
               proj(agg("Customers", "Silhouette", 1), display="Silhouette"),
               proj(agg("Customers", "Monetary", 0), display="Lifetime value"),
               proj(agg("Customers", "Recency", 1), display="Days since last order"),
               proj(col("Customers", "Country")),
           ]},
           title="Call list — highest-value customers closest to a cluster boundary",
           sort=(agg("Customers", "Monetary", 0), "Descending")),
]

# ============================================================================
# Build
# ============================================================================

pages = [
    {"name": "cluster_anatomy", "displayName": "Cluster Anatomy", "visuals": pg1},
    {"name": "cluster_space", "displayName": "Cluster Space", "visuals": pg2},
    {"name": "cluster_geography", "displayName": "Cluster Geography", "visuals": pg3},
    {"name": "boundary_watch", "displayName": "Boundary Watch", "visuals": pg4},
]

errors = validate_report_against_model(pages, model)
if errors:
    print("VALIDATION ERRORS:")
    for e in errors:
        print(" -", e)
    sys.exit(1)

root = write_project(OUT, "SegmentationExplorer", "Cluster Intelligence — Customer Segmentation",
                     model, pages, THEME_SRC, custom_theme=theme)
n_visuals = sum(len(p["visuals"]) for p in pages)
print(f"OK: {root} — {len(pages)} pages, {n_visuals} visuals, "
      f"{len(model['model']['relationships'])} relationships")
