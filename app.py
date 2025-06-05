import os, re, time, datetime, json, tempfile, xml.etree.ElementTree as ET

import requests
import pandas as pd
from faker import Faker
from flask import Flask, render_template, request, redirect, url_for, flash
from typing import Set


app = Flask(__name__)
app.secret_key = "secret"

fake = Faker()                       

# ──────────────────────────────────────────
#  Helpers: masking
# ──────────────────────────────────────────
def mask_value(val):
    if pd.isna(val):
        return val
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return fake.random_int(0, 1000) if isinstance(val, int) else \
               fake.pyfloat(left_digits=3, right_digits=2, positive=True)
    if isinstance(val, (datetime.date, datetime.datetime)):
        return fake.date_object()
    return fake.word()

def mask_dataframe(df: pd.DataFrame, sensitive_cols) -> pd.DataFrame:
    df = df.copy()
    for col in df.columns:
        if col in sensitive_cols:
            df[col] = df[col].apply(mask_value)
    return df

def process_csv_file(path: str, sensitive_cols):
    df = pd.read_csv(path)
    masked = mask_dataframe(df, sensitive_cols)
    out_dir = os.path.join(os.path.dirname(path), "masked")
    os.makedirs(out_dir, exist_ok=True)
    base, ext = os.path.splitext(os.path.basename(path))
    out_path = os.path.join(out_dir, f"{base}_masked{ext}")
    masked.to_csv(out_path, index=False)
    return out_path

# ──────────────────────────────────────────
#  GraphQL settings
# ──────────────────────────────────────────
# GRAPHQL_ENDPOINT = "https://teranet.test.ataccama.online/graphql"
# HEADERS = {
#     "Content-Type": "application/json",
#     "Authorization": "Basic YWRtaW46cmVvdzRyYWlNaWV6ZWlwaWVqdThWb2h4dXBoZWV5ZWU=" 
# }
GRAPHQL_ENDPOINT = "https://teranet.prod.ataccama.online/graphql"
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": "Basic YWRtaW46TGFlZ2V2YWVHYWp1RDlpZXF1ZWljaG9vRG9uaWVwYTA="
}

SENSITIVE_TAGS = {"confidential", "restricted"}

GET_SENSITIVE_ATTRS_BY_LOCATION = """
query GetSensitiveAttributesByLocation($locationGid: GID!) {
  location(gid: $locationGid) {
    draftVersion {
      catalogItems {
        edges {
          node {
            gid
            publishedVersion {
              attributes {
                edges {
                  node {
                    draftVersion { name }
                    publishedVersion {
                      termInstances {
                        edges {
                          node {
                            publishedVersion { displayName }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
"""
def get_sensitive_attributes_for_location(location_gid: str):
    """Return *column names* that should be masked for every catalog item in the location."""
    resp = requests.post(
        GRAPHQL_ENDPOINT,
        json={"query": GET_SENSITIVE_ATTRS_BY_LOCATION,
              "variables": {"locationGid": location_gid}},
        headers=HEADERS
    )
    resp.raise_for_status()
    edges = (resp.json()["data"]["location"]["draftVersion"]
                       ["catalogItems"]["edges"])
    sensitive = set()
    for item in edges:
        attr_edges = (item["node"]["publishedVersion"]["attributes"]["edges"])
        for attr in attr_edges:
            name = attr["node"]["draftVersion"]["name"]
            terms = [ti["node"]["publishedVersion"]["displayName"].strip().lower()
                     for ti in attr["node"]["publishedVersion"]
                                   ["termInstances"]["edges"]]
            if any(t in SENSITIVE_TAGS for t in terms):
                sensitive.add(name)
    return sensitive

# ──────────────────────────────────────────
#  Export‑plan helpers
# ──────────────────────────────────────────
def get_catalog_items_for_location_export(location_gid):
    query = """
    query ($gid: GID!) {
      location(gid: $gid) {
        draftVersion {
          catalogItems { edges { node { gid } } }
        }
      }
    }
    """
    edges = requests.post(GRAPHQL_ENDPOINT,
        json={"query": query, "variables": {"gid": location_gid}},
        headers=HEADERS).json()["data"]["location"]["draftVersion"]["catalogItems"]["edges"]
    return [e["node"]["gid"] for e in edges]

def get_catalog_item_attributes_export(catalog_item_gid):
    query = """
    query ($gid: GID!) {
      catalogItem(gid: $gid) {
        publishedVersion {
          attributes { edges { node { draftVersion { name } } } }
        }
      }
    }
    """
    edges = requests.post(GRAPHQL_ENDPOINT,
        json={"query": query, "variables": {"gid": catalog_item_gid}},
        headers=HEADERS).json()["data"]["catalogItem"]["publishedVersion"]["attributes"]["edges"]
    return [{"name": e["node"]["draftVersion"]["name"], "type": "STRING"} for e in edges]

def store_catalog_data_export(location_gid):
    data = {cid: get_catalog_item_attributes_export(cid)
            for cid in get_catalog_items_for_location_export(location_gid)}
    tmp = tempfile.NamedTemporaryFile(delete=False, mode="w", suffix=".json",
                                      prefix="catalog_data_")
    json.dump(data, tmp, indent=2)
    tmp.close()
    return tmp.name

XML_TEMPLATE = """<?xml version='1.0' encoding='UTF-8'?>
<purity-config version="14.5.1.231204-6829-cc8f270d">
    <references/>
    <component-mappings>
        <propertyMappings/>
    </component-mappings>

<!-- (Catalog Item Reader) --><step mode="NORMAL" className="com.ataccama.dqc.tasks.catalogItems.CatalogItemReader" disabled="false" id="Catalog Item Reader">
    <properties serverName="TeranetTest" catalogItem="PLACEHOLDER_CATALOG_ITEM">
        <columns>
            <!-- Columns will be replaced -->
        </columns>
        <shadowColumns/>
    </properties>
    <visual-constraints layout="vertical" bounds="312,120,48,48"/>
</step>
<connection className="com.ataccama.dqc.model.elements.connections.StandardFlowConnection" disabled="false">
    <source endpoint="out" step="Catalog Item Reader"/>
    <target endpoint="in" step="out"/>
    <visual-constraints>
        <bendpoints/>
    </visual-constraints>
</connection>

<!-- (out) --><step mode="NORMAL" className="com.ataccama.dqc.tasks.io.text.write.TextFileWriter" disabled="false" id="out">
    <properties writeHeader="true" fileName="PLACEHOLDER_CSV" fieldSeparator=";" generateMetadata="true" stringQualifierEscape="&quot;" writeAllColumns="true" compression="NONE" encoding="UTF-8" lineSeparator=" " stringQualifier="&quot;" useStringQualifierOnAllColumns="false">
        <columns/>
        <dataFormatParameters falseValue="false" dateTimeFormat="yyyy-MM-dd HH:mm:ss" decimalSeparator="." dayFormat="yyyy-MM-dd" trueValue="true" dateFormatLocale="en_US" thousandsSeparator=""/>
    </properties>
    <visual-constraints layout="vertical" bounds="408,264,-1,-1"/>
</step>

</purity-config>
"""

def update_export_plan(output_folder, catalog_json_path):
    with open(catalog_json_path, "r", encoding="utf-8") as f:
        catalog_data = json.load(f)

    os.makedirs(output_folder, exist_ok=True)

    for cid, attrs in catalog_data.items():
        # Create the <catalogItemColumn> entries
        columns_xml = ""
        for attr in attrs:
            columns_xml += f'                <catalogItemColumn name="{attr["name"]}" type="{attr["type"]}"/>\n'

        # Prepare XML file by text replacement
        file_content = XML_TEMPLATE
        file_content = file_content.replace("PLACEHOLDER_CATALOG_ITEM", cid)
        file_content = file_content.replace("PLACEHOLDER_CSV", f"ReadInData_{cid}.csv")
        file_content = file_content.replace("<!-- Columns will be replaced -->", columns_xml.rstrip())

        # Write output
        out_path = os.path.join(output_folder, f"export_plan_{cid}.plan")
        with open(out_path, "w", encoding="utf-8") as out_file:
            out_file.write(file_content)


# ──────────────────────────────────────────
#  Flask routes
# ──────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/mask", methods=["POST"])
def mask_files():
    folder = request.form.get("folderPath")
    location_gid = request.form.get("locationGid")
    if not folder or not os.path.isdir(folder):
        flash("Invalid folder path.", "error"); return redirect(url_for("index"))
    if not location_gid:
        flash("Location GID is required.", "error"); return redirect(url_for("index"))

    try:
        sensitive_cols = get_sensitive_attributes_for_location(location_gid)
    except Exception as e:
        flash(f"GraphQL error: {e}", "error"); return redirect(url_for("index"))

    if not sensitive_cols:
        flash("No sensitive attributes found for this location.", "info")
        return redirect(url_for("index"))
    flash("Sensitive columns: " + ", ".join(sorted(sensitive_cols)), "info")

    processed = []
    for csv in (p for p in os.listdir(folder) if p.lower().endswith(".csv")):
        try:
            out = process_csv_file(os.path.join(folder, csv), sensitive_cols)
            processed.append(os.path.basename(out))
        except Exception as e:
            flash(f"Error processing {csv}: {e}", "error")

    flash("Processed: " + ", ".join(processed) if processed else "No files processed.",
          "success" if processed else "error")
    return redirect(url_for("index"))

@app.route("/export")
def export_page():
    return render_template("export.html")

@app.route("/export_process", methods=["POST"])
def export_process():
    locs = request.form.get("location_gid", "")
    output = request.form.get("output_folder", "")
    if not locs or not output:
        flash("Location GIDs and output folder required.", "error")
        return redirect(url_for("export_page"))

    for gid in [l.strip() for l in re.split("[,\\s]+", locs) if l.strip()]:
        try:
            tmp = store_catalog_data_export(gid)
            update_export_plan(output, tmp)
            os.remove(tmp)
            flash(f"Export plans created for {gid}", "success")
        except Exception as e:
            flash(f"Error exporting {gid}: {e}", "error")

    return redirect(url_for("export_page"))

if __name__ == "__main__":
    app.run(debug=True, port=5001)
