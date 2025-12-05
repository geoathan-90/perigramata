import pandas as pd
import ezdxf
from pathlib import Path
import re


CSV_PATH = "diagrams.csv"   # adjust if needed
OUT_DIR = "tower_dxf"       # output folder for DXF files

X_MIN = -15000
X_MAX = 15000

TEXT_HEIGHT = 250
TITLE_HEIGHT = 500

LEFT_LABEL_EXTRA_OFFSET = 2000  # how much further left to place left labels

# Layer names
LAYER_BASE_VARIANTS = "BASE_VARIANTS"
LAYER_OFFSET_VARIANTS = "OFFSET_VARIANTS"   # for / +0,70, / +0,50, / +whatever
LAYER_CENTERLINE = "CENTERLINE"
LAYER_ANNOTATIONS = "ANNOTATIONS"           # all text (labels + title)
LAYER_ANGLED_LINES = "ANGLED_LINES"         # new: the two diagonal lines


def normalize_base(leg_type: str) -> str:
    """
    From a full leg type string like:
        '- 3 / +0,70', '+ 6 / +0,70', ' - 4 (-3,80)', 'N / +0,70'
    get the canonical base string:
        '-3', '6', '-4', 'N'
    """
    s = leg_type.strip()
    # Cut off anything after '/' or '(' -> keep only the base part
    for sep in ("/", "("):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
    # Remove all spaces
    s = s.replace(" ", "")
    # Make '+1' the same as '1'
    if s.startswith("+"):
        s = s[1:]
    return s


def parse_offset_value(leg_type: str):
    """
    Find the numeric part after the '/', e.g. for:
        '-1 / +0,70'   -> 0.70
        'N / +0.50'    -> 0.50
        '+6/+0,70'     -> 0.70
    Returns float or None if no offset is present.
    """
    if "/" not in leg_type:
        return None

    # Part after the first slash
    part = leg_type.split("/", 1)[1]

    # Remove anything in parentheses (e.g. ' (+3,80)')
    part = part.split("(", 1)[0]

    # Regex: first signed number with optional decimal part
    m = re.search(r"[+-]?\d+(?:[.,]\d+)?", part)
    if not m:
        return None

    num_str = m.group(0).replace(",", ".")
    try:
        return float(num_str)
    except ValueError:
        return None


def parse_distance(val):
    """
    Parse 'distance on the ground' cell to float.
    Handles integers or decimals with comma or dot.
    """
    if pd.isna(val):
        return None
    s = str(val).strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def compute_y_maps(df_for_tower: pd.DataFrame):
    """
    For a given tower (subset of the dataframe), compute:
      - base_order: list of base leg types in the order encountered
      - y_base_map: mapping base -> y coordinate for the base variant
      - y_variant_map: mapping full Leg Type string -> y coordinate

    Pattern:
        Base:
          - base 'N' -> y = 0
          - base integer k -> y = -1000 * k
        Offset:
          - if we have '/ +x' -> y = y_base - x * 1000
    """
    unique_leg_types = df_for_tower["Leg Type"].unique()

    base_order = []
    y_base_map = {}
    y_variant_map = {}

    for lt in unique_leg_types:
        base = normalize_base(lt)

        # Determine (and remember) the base y
        if base not in y_base_map:
            if base == "N":
                y_base = 0
            else:
                # If the base is numeric, map k -> -1000 * k
                try:
                    k = int(base)
                except ValueError:
                    # Fallback if something weird appears: treat as 0
                    k = 0
                y_base = -1000 * k
            y_base_map[base] = y_base
            base_order.append(base)
        else:
            y_base = y_base_map[base]

        # Offset handling: / +x -> y = y_base - x * 1000
        offset = parse_offset_value(lt)
        if offset is not None:
            y = y_base - round(offset * 1000)
        else:
            y = y_base

        y_variant_map[lt] = y

    if "N" not in y_base_map:
        raise ValueError("Expected a base 'N' level in this tower, but didn't find one.")

    return base_order, y_base_map, y_variant_map


def ensure_layers(doc):
    """Create layers if they don't exist yet."""
    if LAYER_BASE_VARIANTS not in doc.layers:
        doc.layers.new(name=LAYER_BASE_VARIANTS, dxfattribs={"color": 7})  # white
    if LAYER_OFFSET_VARIANTS not in doc.layers:
        doc.layers.new(name=LAYER_OFFSET_VARIANTS, dxfattribs={"color": 1})  # red
    if LAYER_CENTERLINE not in doc.layers:
        doc.layers.new(name=LAYER_CENTERLINE, dxfattribs={"color": 3})  # green
    if LAYER_ANNOTATIONS not in doc.layers:
        doc.layers.new(name=LAYER_ANNOTATIONS, dxfattribs={"color": 2})  # yellow-ish
    if LAYER_ANGLED_LINES not in doc.layers:
        doc.layers.new(name=LAYER_ANGLED_LINES, dxfattribs={"color": 4})  # cyan-ish


def draw_tower(doc, tower_name: str, df_for_tower: pd.DataFrame):
    """
    Draws:
      - one horizontal line for each unique Leg Type (variant),
        from X_MIN to X_MAX at its y position.
      - labels (variant name) at both ends of each line (on ANNOTATIONS layer).
      - a dashed vertical centerline.
      - two angled lines based on 'distance on the ground'.
      - a title with the tower type above the topmost line (on ANNOTATIONS layer).
    """
    ensure_layers(doc)
    msp = doc.modelspace()

    _, _, y_variant_map = compute_y_maps(df_for_tower)

    all_y = list(y_variant_map.values())
    if not all_y:
        return  # nothing to draw

    y_max = max(all_y)
    y_min = min(all_y)

    # Draw one line per variant
    for leg_type, y in y_variant_map.items():
        label = str(leg_type).strip()

        # Decide if this variant is an offset variant (has an offset value)
        offset_value = parse_offset_value(leg_type)
        is_offset_variant = offset_value is not None
        layer_name = LAYER_OFFSET_VARIANTS if is_offset_variant else LAYER_BASE_VARIANTS

        # Horizontal line (on base/offset layer)
        msp.add_line(
            (X_MIN, y),
            (X_MAX, y),
            dxfattribs={"layer": layer_name},
        )

        # Left label: placed further to the left than the line, on ANNOTATIONS layer
        left_x = X_MIN - LEFT_LABEL_EXTRA_OFFSET
        t1 = msp.add_text(
            label,
            dxfattribs={
                "height": TEXT_HEIGHT,
                "layer": LAYER_ANNOTATIONS,
            },
        )
        t1.dxf.insert = (left_x, y + TEXT_HEIGHT)  # NO set_pos!

        # Right label: at the right end of the line, slightly above, on ANNOTATIONS layer
        t2 = msp.add_text(
            label,
            dxfattribs={
                "height": TEXT_HEIGHT,
                "layer": LAYER_ANNOTATIONS,
            },
        )
        t2.dxf.insert = (X_MAX, y + TEXT_HEIGHT)  # NO set_pos!

    # ---------- Angled lines based on "distance on the ground" ----------

    # Find leg types for lowest and highest horizontal lines
    lowest_leg_type = min(y_variant_map, key=lambda lt: y_variant_map[lt])
    highest_leg_type = max(y_variant_map, key=lambda lt: y_variant_map[lt])

    y_low = y_variant_map[lowest_leg_type]
    y_high = y_variant_map[highest_leg_type]

    # Get their corresponding 'distance on the ground' values
    col_dist = "distance on the ground"  # column name as in your CSV

    # Lowest
    df_low = df_for_tower[df_for_tower["Leg Type"] == lowest_leg_type]
    x_low = None
    if not df_low.empty and col_dist in df_low.columns:
        x_low = parse_distance(df_low.iloc[0][col_dist])

    # Highest
    df_high = df_for_tower[df_for_tower["Leg Type"] == highest_leg_type]
    x_high = None
    if not df_high.empty and col_dist in df_high.columns:
        x_high = parse_distance(df_high.iloc[0][col_dist])

    if x_low is not None and x_high is not None:
        # Positive side angled line: from lowest to highest
        # Example you gave: (8998, -6700) to (7616, 4000)
        msp.add_line(
            (x_low, y_low),
            (x_high, y_high),
            dxfattribs={"layer": LAYER_ANGLED_LINES},
        )

        # Negative side: mirrored around the centerline (x -> -x)
        msp.add_line(
            (-x_low, y_low),
            (-x_high, y_high),
            dxfattribs={"layer": LAYER_ANGLED_LINES},
        )

    # ---------- Centerline ----------

    # Dashed vertical centerline at x=0 (on CENTERLINE layer)
    centerline_top = y_max + 1000
    centerline_bottom = y_min - 1000
    msp.add_line(
        (0, centerline_bottom),
        (0, centerline_top),
        dxfattribs={
            "layer": LAYER_CENTERLINE,
            "linetype": "CENTER",  # relies on ezdxf.new(setup=True)
        },
    )

    # ---------- Title ----------

    # Title somewhere up top (above the highest line), on ANNOTATIONS layer
    title_y = y_max + 2000  # some margin above the highest line
    title = f"Tower Type {tower_name}"
    title_text = msp.add_text(
        title,
        dxfattribs={
            "height": TITLE_HEIGHT,
            "layer": LAYER_ANNOTATIONS,
        },
    )
    # Center-ish above the lines
    title_text.dxf.insert = (0, title_y)


def main():
    df = pd.read_csv(CSV_PATH)

    out_dir = Path(OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Tower types in the order they appear in the CSV:
    tower_types = df["Tower Type"].unique()

    for tower in tower_types:
        df_tower = df[df["Tower Type"] == tower]

        # Create a new DXF document for each tower type
        doc = ezdxf.new(setup=True)
        draw_tower(doc, tower, df_tower)

        # Sanitize filename a bit
        safe_name = (
            str(tower)
            .replace("+", "plus")
            .replace("/", "_")
            .replace(" ", "")
        )
        out_path = out_dir / f"{safe_name}.dxf"
        doc.saveas(out_path)
        print(f"Saved {out_path}")


if __name__ == "__main__":
    main()
