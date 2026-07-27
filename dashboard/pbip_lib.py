# -*- coding: utf-8 -*-
"""Library for generating Power BI Project (PBIP) dashboards with PBIR reports.

Produces the full tree:
  <Name>.pbip
  <Name>.Report/           (.platform, definition.pbir, definition/..., StaticResources/...)
  <Name>.SemanticModel/    (.platform, definition.pbism, model.bim)

Formats verified against Microsoft Learn PBIP docs, the microsoft/json-schemas
repo, and a real-world PBIR example report (schema visualContainer 2.4.0).
"""
import csv
import json
import shutil
import uuid
from pathlib import Path

VC_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.4.0/schema.json"
PAGE_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json"
PAGES_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.0.0/schema.json"
REPORT_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/report/3.0.0/schema.json"
VERSION_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/versionMetadata/1.0.0/schema.json"
PBIR_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json"
PBISM_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json"
PBIP_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json"
PLATFORM_SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json"

BASE_THEME = "CY24SU10"

# M type per model dataType
_M_TYPES = {"string": "type text", "int64": "Int64.Type", "double": "type number",
            "dateTime": "type date", "boolean": "type logical"}


def _guid():
    return str(uuid.uuid4())


def lit(value):
    """Literal expression wrapper."""
    return {"expr": {"Literal": {"Value": value}}}


def slit(text):
    """String literal (single-quoted, quotes doubled)."""
    return lit("'" + str(text).replace("'", "''") + "'")


# ============================================================================
# Field references & projections
# ============================================================================

def col(entity, prop):
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def meas(entity, prop):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def agg(entity, prop, fn=0):
    """Aggregation over a column. fn: 0=Sum 1=Avg 2=DistinctCount 3=Min 4=Max 5=Count"""
    return {"Aggregation": {"Expression": {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}, "Function": fn}}


_AGG_NAMES = {0: "Sum", 1: "Avg", 2: "CountNonNull", 3: "Min", 4: "Max", 5: "Count"}


def proj(field, display=None):
    """Build a projection from a field reference dict."""
    if "Column" in field:
        entity = field["Column"]["Expression"]["SourceRef"]["Entity"]
        prop = field["Column"]["Property"]
        qref = f"{entity}.{prop}"
        native = prop
    elif "Measure" in field:
        entity = field["Measure"]["Expression"]["SourceRef"]["Entity"]
        prop = field["Measure"]["Property"]
        qref = f"{entity}.{prop}"
        native = prop
    elif "Aggregation" in field:
        inner = field["Aggregation"]["Expression"]["Column"]
        entity = inner["Expression"]["SourceRef"]["Entity"]
        prop = inner["Property"]
        fn = _AGG_NAMES[field["Aggregation"]["Function"]]
        qref = f"{fn}({entity}.{prop})"
        native = f"{fn} of {prop}"
    else:
        raise ValueError(f"Unknown field type: {field}")
    p = {"field": field, "queryRef": qref, "nativeQueryRef": native}
    if display:
        p["displayName"] = display
    return p


# ============================================================================
# Visual builders
# ============================================================================

def _title_obj(text, size="12"):
    return {"title": [{"properties": {
        "show": lit("true"),
        "text": slit(text),
        "fontSize": lit(f"{size}D"),
    }}]}


def visual(name, vtype, x, y, w, h, roles=None, title=None, sort=None,
           objects=None, vc_objects=None, filters=None, z=0, no_default_interact=False):
    """Generic visual.json builder.

    roles: {"Category": [proj,...], "Y": [proj,...], ...}
    sort:  (field, "Descending"|"Ascending") or list of those
    filters: list of filterConfig filter dicts
    """
    v = {
        "$schema": VC_SCHEMA,
        "name": name,
        "position": {"x": x, "y": y, "z": z, "width": w, "height": h},
        "visual": {
            "visualType": vtype,
            "drillFilterOtherVisuals": True,
        },
    }
    if roles:
        query = {"queryState": {r: {"projections": ps} for r, ps in roles.items()}}
        if sort:
            sorts = sort if isinstance(sort, list) else [sort]
            query["sortDefinition"] = {
                "sort": [{"field": f, "direction": d} for f, d in sorts],
                "isDefaultSort": True,
            }
        v["visual"]["query"] = query
    if objects:
        v["visual"]["objects"] = objects
    vco = dict(vc_objects or {})
    if title:
        vco.update(_title_obj(title))
    if vco:
        v["visual"]["visualContainerObjects"] = vco
    if filters:
        v["filterConfig"] = {"filters": filters}
    return v


def default_color(hex_color):
    """objects entry: single fill color for all data points of a visual."""
    return {"dataPoint": [{"properties": {
        "defaultColor": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{hex_color}'"}}}}}}}]}


def category_colors(entity, prop, mapping, extra=None):
    """objects entry: per-category fill colors via scopeId selectors.

    mapping: {"High": "#E14B4B", ...}
    """
    entries = list(extra or [])
    for value, hex_color in mapping.items():
        entries.append({
            "properties": {"fill": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{hex_color}'"}}}}}},
            "selector": {"data": [{"scopeId": {"Comparison": {
                "ComparisonKind": 0,
                "Left": {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}},
                "Right": {"Literal": {"Value": "'" + value.replace("'", "''") + "'"}},
            }}}]},
        })
    return {"dataPoint": entries}


def card(name, measure_field, x, y, w=240, h=100, title=None, accent=None,
         show_category=False):
    v = visual(name, "card", x, y, w, h, roles={"Values": [proj(measure_field)]}, title=title)
    objects = {
        "labels": [{"properties": {"fontSize": lit("24D"), "labelDisplayUnits": lit("0D")}}],
        # The category label repeats the measure name directly under the value,
        # which duplicates the visual title and clips in short cards.
        "categoryLabels": [{"properties": {"show": lit("true" if show_category else "false")}}],
    }
    if accent:
        objects["labels"][0]["properties"]["color"] = {
            "solid": {"color": {"expr": {"Literal": {"Value": f"'{accent}'"}}}}}
    v["visual"]["objects"] = objects
    return v


def azure_map(name, x, y, w, h, roles, title=None, colors=None,
              min_radius=6, max_radius=22):
    """Azure Maps bubble layer — the supported replacement for the retiring
    Bing `map` visual. Zoom/centre are deliberately left unset so the visual
    auto-fits to whatever the slicers leave on screen."""
    v = visual(name, "azureMap", x, y, w, h, roles=roles, title=title)
    objects = {
        "mapControls": [{"properties": {
            "defaultStyle": slit("road"),
            "showStylePicker": lit("false"),
            "showNavigationControls": lit("false"),
            "showSelectionControl": lit("false"),
        }}],
        "bubbleLayer": [{"properties": {
            "show": lit("true"),
            "minBubbleRadius": lit(f"{min_radius}L"),
            "maxRadius": lit(f"{max_radius}L"),
            "bubbleStrokeWidth": lit("1L"),
            "autoStrokeColor": lit("true"),
        }}],
    }
    if colors:
        objects.update(colors)
    v["visual"]["objects"] = objects
    return v


def slicer(name, column_field, x, y, w, h, title=None, dropdown=False, sync_group=None):
    v = visual(name, "slicer", x, y, w, h, roles={"Values": [proj(column_field)]}, title=title)
    objects = {}
    if dropdown:
        objects["data"] = [{"properties": {"mode": slit("Dropdown")}}]
    if title:
        # The slicer's own header repeats the field name directly under the
        # visual title; hiding it removes the duplicate and frees a row.
        objects["header"] = [{"properties": {"show": lit("false")}}]
    if objects:
        v["visual"]["objects"] = objects
    if sync_group:
        # Slicers sharing a groupName keep the same selection across pages —
        # essential for the light/dark page-twin toggle to feel seamless
        v["visual"]["syncGroup"] = {"groupName": sync_group,
                                    "fieldChanges": True, "filterChanges": True}
    return v


def action_button(name, label, target_page, x, y, w, h,
                  fill="#FFFFFF", font_color="#1B2A41", border_color=None):
    """Page-navigation button (used for the light/dark mode toggle)."""
    return {
        "$schema": VC_SCHEMA,
        "name": name,
        "position": {"x": x, "y": y, "z": 2000, "width": w, "height": h},
        "visual": {
            "visualType": "actionButton",
            "objects": {
                "text": [{"properties": {
                    "show": lit("true"),
                    "text": slit(label),
                    "fontColor": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{font_color}'"}}}}},
                    "fontSize": lit("10D"),
                }, "selector": {"id": "default"}}],
                "fill": [{"properties": {
                    "show": lit("true"),
                    "fillColor": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{fill}'"}}}}},
                    "transparency": lit("0D"),
                }, "selector": {"id": "default"}}],
                "outline": [{"properties": {"show": lit(
                    "true" if border_color else "false")} | (
                    {"lineColor": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{border_color}'"}}}}}}
                    if border_color else {}),
                    "selector": {"id": "default"}}],
            },
            "visualContainerObjects": {
                "visualLink": [{"properties": {
                    "show": lit("true"),
                    "type": slit("PageNavigation"),
                    "navigationSection": slit(target_page),
                }}],
            },
            "drillFilterOtherVisuals": True,
        },
    }


def textbox(name, text, x, y, w, h, size="20pt", weight="600", color=None,
            bg_color=None, subtitle=None, subtitle_color=None):
    run = {"value": text, "textStyle": {"fontFamily": "Segoe UI", "fontSize": size, "fontWeight": weight}}
    if color:
        run["textStyle"]["color"] = color
    paragraphs = [{"textRuns": [run]}]
    if subtitle:
        paragraphs.append({"textRuns": [{
            "value": subtitle,
            "textStyle": {"fontFamily": "Segoe UI", "fontSize": "10pt",
                          "color": subtitle_color or "#B9C4D0"},
        }]})
    if bg_color:
        background = [{"properties": {
            "show": lit("true"),
            "color": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{bg_color}'"}}}}},
            "transparency": lit("0D"),
        }}]
    else:
        background = [{"properties": {"show": lit("false")}}]
    return {
        "$schema": VC_SCHEMA,
        "name": name,
        "position": {"x": x, "y": y, "z": 1000, "width": w, "height": h},
        "visual": {
            "visualType": "textbox",
            "objects": {"general": [{"properties": {"paragraphs": paragraphs}}]},
            "visualContainerObjects": {
                "title": [{"properties": {"show": lit("false")}}],
                "background": background,
                "border": [{"properties": {"show": lit("false")}}],
                "dropShadow": [{"properties": {"show": lit("false")}}],
            },
            "drillFilterOtherVisuals": True,
        },
    }


def categorical_filter(name, entity, prop, values, value_type="text"):
    """Visual-level categorical filter pinned to specific values."""
    if value_type == "text":
        vals = [[{"Literal": {"Value": f"'{v}'"}}] for v in values]
    else:
        vals = [[{"Literal": {"Value": f"{v}L"}}] for v in values]
    return {
        "name": name,
        "field": col(entity, prop),
        "type": "Categorical",
        "filter": {
            "Version": 2,
            "From": [{"Name": "f", "Entity": entity, "Type": 0}],
            "Where": [{"Condition": {"In": {
                "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": prop}}],
                "Values": vals,
            }}}],
        },
        "howCreated": "User",
    }


# ============================================================================
# Semantic model (model.bim / TMSL)
# ============================================================================

def table_from_csv(name, csv_path, types, summarize=None, sort_by=None,
                   format_strings=None, measures=None, data_categories=None):
    """Build a TMSL table dict whose partition reads the CSV.

    types: {column: dataType} — must cover every CSV header (validated).
    summarize: columns allowed implicit sum (default: none for all)
    sort_by: {column: sort_by_column}
    format_strings: {column: format}
    measures: [{"name","expression","formatString"}]
    data_categories: {column: "Country"|"City"|"Place"|...} — required for map
        visuals, which only geocode columns whose data category marks them
        as geographic.
    """
    csv_path = Path(csv_path)
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        headers = next(csv.reader(f))

    missing = [h for h in headers if h not in types]
    extra = [t for t in types if t not in headers]
    if missing or extra:
        raise ValueError(f"{name}: type map mismatch. missing={missing} extra={extra}")

    summarize = summarize or set()
    sort_by = sort_by or {}
    format_strings = format_strings or {}
    data_categories = data_categories or {}

    columns = []
    for h in headers:
        c = {
            "name": h,
            "dataType": types[h],
            "sourceColumn": h,
            "lineageTag": _guid(),
            "summarizeBy": "sum" if h in summarize else "none",
            "annotations": [{"name": "SummarizationSetBy", "value": "User"}],
        }
        if h in sort_by:
            c["sortByColumn"] = sort_by[h]
        if h in format_strings:
            c["formatString"] = format_strings[h]
        if h in data_categories:
            c["dataCategory"] = data_categories[h]
        if types[h] == "dateTime":
            c["formatString"] = format_strings.get(h, "yyyy-mm-dd")
            c["annotations"].append({"name": "UnderlyingDateTimeDataType", "value": "Date"})
        columns.append(c)

    type_pairs = ", ".join(
        '{"%s", %s}' % (h.replace('"', '""'), _M_TYPES[types[h]]) for h in headers
    )
    # QuoteStyle (NOT QuotePosition) is the valid Csv.Document option; explicit
    # en-US culture makes number/date parsing independent of regional settings
    expression = [
        "let",
        f'    Source = Csv.Document(File.Contents("{csv_path}"),[Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.Csv]),',
        '    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),',
        f'    #"Changed Type" = Table.TransformColumnTypes(#"Promoted Headers",{{{type_pairs}}}, "en-US")',
        "in",
        '    #"Changed Type"',
    ]

    t = {
        "name": name,
        "lineageTag": _guid(),
        "columns": columns,
        "partitions": [{
            "name": name,
            "mode": "import",
            "source": {"type": "m", "expression": expression},
        }],
        "annotations": [{"name": "PBI_ResultType", "value": "Table"}],
    }
    if measures:
        t["measures"] = [
            {"name": m["name"], "expression": m["expression"],
             "formatString": m.get("formatString", "0"), "lineageTag": _guid()}
            for m in measures
        ]
    return t


def build_model(name, tables, relationships=None):
    model = {
        "name": name,
        "compatibilityLevel": 1550,
        "model": {
            "culture": "en-US",
            "dataAccessOptions": {"legacyRedirects": True, "returnErrorValuesAsNull": True},
            "defaultPowerBIDataSourceVersion": "powerBI_V3",
            "sourceQueryCulture": "en-US",
            "tables": tables,
            "annotations": [
                {"name": "PBI_QueryOrder", "value": json.dumps([t["name"] for t in tables])},
                {"name": "__PBI_TimeIntelligenceEnabled", "value": "0"},
            ],
        },
    }
    if relationships:
        model["model"]["relationships"] = [
            {"name": _guid(), "fromTable": r[0], "fromColumn": r[1],
             "toTable": r[2], "toColumn": r[3]}
            for r in relationships
        ]
    return model


# ============================================================================
# Validation: every visual field must exist in the model
# ============================================================================

def _iter_field_refs(obj):
    if isinstance(obj, dict):
        for key in ("Column", "Measure"):
            if key in obj and isinstance(obj[key], dict) and "Property" in obj[key]:
                src = obj[key].get("Expression", {}).get("SourceRef", {})
                if "Entity" in src:
                    yield key, src["Entity"], obj[key]["Property"]
        for v in obj.values():
            yield from _iter_field_refs(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_field_refs(v)


def validate_report_against_model(pages, model):
    cols, meas_ = {}, {}
    for t in model["model"]["tables"]:
        cols[t["name"]] = {c["name"] for c in t["columns"]}
        meas_[t["name"]] = {m["name"] for m in t.get("measures", [])}
    errors = []
    for page in pages:
        for v in page["visuals"]:
            for kind, entity, prop in _iter_field_refs(v):
                if entity not in cols:
                    errors.append(f"{page['name']}/{v['name']}: unknown table '{entity}'")
                elif kind == "Column" and prop not in cols[entity]:
                    errors.append(f"{page['name']}/{v['name']}: unknown column '{entity}'.'{prop}'")
                elif kind == "Measure" and prop not in meas_[entity]:
                    errors.append(f"{page['name']}/{v['name']}: unknown measure '{entity}'.'{prop}'")
    # sortByColumn integrity
    for t in model["model"]["tables"]:
        names = {c["name"] for c in t["columns"]}
        for c in t["columns"]:
            if "sortByColumn" in c and c["sortByColumn"] not in names:
                errors.append(f"model {t['name']}.{c['name']}: sortByColumn '{c['sortByColumn']}' missing")
    for r in model["model"].get("relationships", []):
        for tbl, colname in ((r["fromTable"], r["fromColumn"]), (r["toTable"], r["toColumn"])):
            if colname not in cols.get(tbl, set()):
                errors.append(f"relationship: {tbl}.{colname} missing")
    return errors


# ============================================================================
# Project writer
# ============================================================================

def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def make_theme(name, data_colors, page_bg, fg, accent, table_accent=None,
               border_color=None):
    """Custom report theme: palette + card-style visuals + typography."""
    grey_border = border_color or "#E1E7EE"
    return {
        "name": name,
        "dataColors": data_colors,
        "background": "#FFFFFF",
        "foreground": fg,
        "tableAccent": table_accent or accent,
        "textClasses": {
            "callout": {"fontSize": 26, "fontFace": "Segoe UI Semibold", "color": fg},
            "title": {"fontSize": 11, "fontFace": "Segoe UI Semibold", "color": "#53606E"},
            "header": {"fontSize": 12, "fontFace": "Segoe UI Semibold", "color": fg},
            "label": {"fontSize": 9, "fontFace": "Segoe UI", "color": "#53606E"},
        },
        "visualStyles": {
            "*": {"*": {
                "background": [{"show": True, "color": {"solid": {"color": "#FFFFFF"}}, "transparency": 0}],
                "border": [{"show": True, "color": {"solid": {"color": grey_border}}, "radius": 8}],
                "dropShadow": [{"show": False}],
                "title": [{"show": True, "fontColor": {"solid": {"color": "#53606E"}},
                           "fontSize": 11, "fontFamily": "Segoe UI Semibold"}],
                "outspacePane": [{"backgroundColor": {"solid": {"color": "#FFFFFF"}}}],
            }},
            "page": {"*": {
                "background": [{"color": {"solid": {"color": page_bg}}, "transparency": 0}],
                "outspace": [{"color": {"solid": {"color": page_bg}}, "transparency": 0}],
            }},
        },
    }


def write_project(root, name, display_name, model, pages, theme_src, active_page=None,
                  custom_theme=None):
    """Write the complete PBIP project. pages: [{"name","displayName","visuals":[...]}]"""
    root = Path(root)
    if root.exists():
        shutil.rmtree(root)
    report_dir = root / f"{name}.Report"
    sm_dir = root / f"{name}.SemanticModel"

    # ---- .pbip
    _write_json(root / f"{name}.pbip", {
        "$schema": PBIP_SCHEMA,
        "version": "1.0",
        "artifacts": [{"report": {"path": f"{name}.Report"}}],
        "settings": {"enableAutoRecovery": True},
    })
    (root / ".gitignore").write_text("**/.pbi/localSettings.json\n**/.pbi/cache.abf\n", encoding="utf-8")

    # ---- SemanticModel
    _write_json(sm_dir / ".platform", {
        "$schema": PLATFORM_SCHEMA,
        "metadata": {"type": "SemanticModel", "displayName": display_name},
        "config": {"version": "2.0", "logicalId": _guid()},
    })
    _write_json(sm_dir / "definition.pbism", {
        "$schema": PBISM_SCHEMA, "version": "4.0", "settings": {}})
    _write_json(sm_dir / "model.bim", model)

    # ---- Report
    _write_json(report_dir / ".platform", {
        "$schema": PLATFORM_SCHEMA,
        "metadata": {"type": "Report", "displayName": display_name},
        "config": {"version": "2.0", "logicalId": _guid()},
    })
    _write_json(report_dir / "definition.pbir", {
        "$schema": PBIR_SCHEMA,
        "version": "4.0",
        "datasetReference": {"byPath": {"path": f"../{name}.SemanticModel"}},
    })
    ddir = report_dir / "definition"
    _write_json(ddir / "version.json", {"$schema": VERSION_SCHEMA, "version": "2.0.0"})

    theme_collection = {"baseTheme": {
        "name": BASE_THEME,
        "reportVersionAtImport": {"visual": "1.8.95", "report": "2.0.95", "page": "1.3.95"},
        "type": "SharedResources",
    }}
    resource_packages = [{
        "name": "SharedResources", "type": "SharedResources",
        "items": [{"name": BASE_THEME, "path": f"BaseThemes/{BASE_THEME}.json", "type": "BaseTheme"}],
    }]
    if custom_theme:
        theme_file = custom_theme["name"] + ".json"
        theme_collection["customTheme"] = {
            "name": theme_file,
            "reportVersionAtImport": {"visual": "2.1.0", "report": "2.1.0", "page": "2.0.0"},
            "type": "RegisteredResources",
        }
        resource_packages.append({
            "name": "RegisteredResources", "type": "RegisteredResources",
            "items": [{"name": theme_file, "path": theme_file, "type": "CustomTheme"}],
        })
        _write_json(report_dir / "StaticResources" / "RegisteredResources" / theme_file,
                    custom_theme)

    _write_json(ddir / "report.json", {
        "$schema": REPORT_SCHEMA,
        "themeCollection": theme_collection,
        "filterConfig": {"filters": []},
        "settings": {
            "useStylableVisualContainerHeader": True,
            "useEnhancedTooltips": True,
            "defaultDrillFilterOtherVisuals": True,
        },
        "resourcePackages": resource_packages,
    })
    theme_dst = report_dir / "StaticResources" / "SharedResources" / "BaseThemes" / f"{BASE_THEME}.json"
    theme_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(theme_src, theme_dst)

    _write_json(ddir / "pages" / "pages.json", {
        "$schema": PAGES_SCHEMA,
        "pageOrder": [p["name"] for p in pages],
        "activePageName": active_page or pages[0]["name"],
    })
    for p in pages:
        pdir = ddir / "pages" / p["name"]
        page_json = {
            "$schema": PAGE_SCHEMA,
            "name": p["name"],
            "displayName": p["displayName"],
            "displayOption": "FitToPage",
            "height": 720,
            "width": 1280,
        }
        if p.get("visibility"):
            page_json["visibility"] = p["visibility"]
        if p.get("objects"):
            page_json["objects"] = p["objects"]
        if p.get("interactions"):
            page_json["visualInteractions"] = p["interactions"]
        _write_json(pdir / "page.json", page_json)
        for v in p["visuals"]:
            _write_json(pdir / "visuals" / v["name"] / "visual.json", v)

    return root


def page_background(color):
    """page.json objects entry: solid page background (overrides theme)."""
    return {"background": [{"properties": {
        "color": {"solid": {"color": {"expr": {"Literal": {"Value": f"'{color}'"}}}}},
        "transparency": lit("0D"),
    }}]}


def _solid(color):
    return {"solid": {"color": {"expr": {"Literal": {"Value": f"'{color}'"}}}}}


_CHART_TYPES = {"clusteredBarChart", "clusteredColumnChart", "lineChart",
                "scatterChart", "donutChart", "pieChart", "areaChart"}


def apply_dark(v, card_bg, border, text, muted):
    """Post-process a visual for a dark page: dark card, light text, themed axes."""
    vis = v.get("visual")
    if not vis:
        return v
    vtype = vis.get("visualType")
    vco = vis.setdefault("visualContainerObjects", {})

    if vtype == "textbox":
        # Header bands already use a dark background — leave as-is
        pass
    elif vtype == "actionButton":
        pass
    else:
        vco["background"] = [{"properties": {
            "show": lit("true"), "color": _solid(card_bg), "transparency": lit("0D")}}]
        vco["border"] = [{"properties": {
            "show": lit("true"), "color": _solid(border), "radius": lit("8D")}}]
        if "title" in vco and vco["title"]:
            vco["title"][0]["properties"]["fontColor"] = _solid(text)

    objects = vis.setdefault("objects", {})
    if vtype == "card":
        objects.setdefault("labels", [{"properties": {}}])
        objects["labels"][0]["properties"]["color"] = _solid(text)
        objects["categoryLabels"] = [{"properties": {"color": _solid(muted)}}]
    elif vtype == "slicer":
        objects["header"] = [{"properties": {"fontColor": _solid(text)}}]
        objects["items"] = [{"properties": {"fontColor": _solid(text)}}]
    elif vtype in _CHART_TYPES:
        for axis in ("categoryAxis", "valueAxis"):
            entry = objects.setdefault(axis, [{"properties": {}}])
            entry[0]["properties"]["labelColor"] = _solid(muted)
        objects.setdefault("legend", [{"properties": {}}])
        objects["legend"][0]["properties"]["labelColor"] = _solid(muted)
    elif vtype in ("tableEx", "pivotTable"):
        objects["columnHeaders"] = [{"properties": {
            "fontColor": _solid(text), "backColor": _solid(card_bg)}}]
        objects["values"] = [{"properties": {
            "fontColorPrimary": _solid(text), "fontColorSecondary": _solid(text),
            "backColorPrimary": _solid(card_bg), "backColorSecondary": _solid(card_bg)}}]
        if vtype == "pivotTable":
            objects["rowHeaders"] = [{"properties": {
                "fontColor": _solid(text), "backColor": _solid(card_bg)}}]
    return v
